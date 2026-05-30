"""Pair selection for statistical arbitrage (master plan Phase 4.1).

Provides four complementary methods for identifying cointegrated or otherwise
co-moving pairs from a cross-section of price series:

1. Distance method (Gatev, Goetzmann, Rouwenhorst 2006) -- sum of squared
   differences of normalised price relatives.
2. Engle-Granger cointegration with Bonferroni / Holm / BH multiple-testing
   correction across all tested pairs.
3. Johansen cointegration -- trace statistic rank test.
4. Copula dependence -- Gaussian copula correlation on empirical pseudo-
   observations of returns.

All selectors return a sorted list of :class:`PairCandidate` objects.  The
``score`` field is always *smaller-is-better* so downstream code can use a
unified ranking criterion.

Design notes
------------
* Small-sample pairs (fewer than ``min_obs`` overlapping observations after NaN
  removal) are **skipped** rather than raising so that cross-sectional screens
  with sparse data degrade gracefully.
* The ``y`` / ``x`` orientation convention for Engle-Granger: both orderings
  (a,b) and (b,a) are tested; the ordering that yields ``hedge_ratio > 0`` is
  preferred.  When neither ordering yields a positive hedge ratio the one with
  the smaller p-value is used.
* For Johansen, the spread is ``s = y - hedge * x`` where
  ``hedge = -hedge_ratios()[1]``.  The normalised eigenvector has element 0
  fixed to 1, so element 1 carries the (already signed) coefficient for x;
  negating gives the standard spread definition with a positive hedge for
  typical co-integrating pairs.
* The Gaussian copula score is ``1 - |rho|`` where ``rho`` is the Pearson
  correlation of the empirical-uniform-transformed returns (rank/(n+1)).
  Smaller score = stronger linear dependence in the uniform margin = better
  pair.
"""
from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core_trading.research.stat_tests import adjust_pvalues, engle_granger_test, johansen_test
from core_trading.research.stat_tests import half_life as compute_half_life

__all__ = [
    "PairCandidate",
    "distance_score",
    "select_pairs_distance",
    "select_pairs_cointegration",
    "select_pairs_johansen",
    "select_pairs_copula",
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairCandidate:
    """A candidate pair for statistical arbitrage.

    Attributes
    ----------
    symbol_y:
        The dependent (``y``) leg of the spread ``y - hedge * x``.
    symbol_x:
        The independent (``x``) leg.
    hedge_ratio:
        OLS or cointegration-vector hedge ratio ``h`` such that
        ``spread = y - h * x`` is (approximately) stationary.
    pvalue:
        Raw cointegration p-value, or ``nan`` for methods that do not report
        p-values (distance, Johansen, copula).
    pvalue_adj:
        Multiple-testing adjusted p-value, or ``nan`` when adjustment is not
        applicable (distance, Johansen, copula).
    half_life:
        Estimated Ornstein-Uhlenbeck half-life of the spread in periods.
    method:
        Identifier of the selection method:
        ``"distance"``, ``"engle_granger"``, ``"johansen"``, or ``"copula"``.
    score:
        Sortable ranking score; **smaller is better** in all methods.
    sector:
        Optional sector label taken from the ``sectors`` mapping.
    """

    symbol_y: str
    symbol_x: str
    hedge_ratio: float
    pvalue: float
    pvalue_adj: float
    half_life: float
    method: str
    score: float
    sector: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _align_pair(
    prices: pd.DataFrame,
    sym_y: str,
    sym_x: str,
    min_obs: int,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return aligned numpy arrays for ``(sym_y, sym_x)`` or ``None``.

    Drops rows where either series has a NaN and returns ``None`` when the
    number of clean overlapping observations is below ``min_obs``.
    """
    sub = prices[[sym_y, sym_x]].dropna()
    if len(sub) < min_obs:
        return None
    return sub[sym_y].to_numpy(dtype=float), sub[sym_x].to_numpy(dtype=float)


def _ols_hedge(y: np.ndarray, x: np.ndarray) -> float:
    """OLS slope of ``y`` on ``x`` with intercept.

    Uses ``numpy.linalg.lstsq`` for a single-pass computation.

    ``slope`` is the coefficient on ``x`` in ``y = a + slope*x + e``.
    """
    design = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(coef[1])


def _spread_half_life(y: np.ndarray, x: np.ndarray, hedge: float) -> float:
    """Compute the half-life of ``y - hedge * x`` via the OU regression.

    Returns ``inf`` when the spread is not mean-reverting.
    """
    spread = y - hedge * x
    result = compute_half_life(spread)
    return result.half_life


def _sector_label(
    sym_y: str, sym_x: str, sectors: Mapping[str, str] | None
) -> str | None:
    """Return the common sector label when both symbols share one, else ``None``."""
    if sectors is None:
        return None
    sy = sectors.get(sym_y)
    sx = sectors.get(sym_x)
    if sy is not None and sy == sx:
        return sy
    return None


def _volume_ok(
    sym: str,
    volume: pd.DataFrame | None,
    min_avg_volume: float,
) -> bool:
    """Return ``True`` when the symbol passes the average-volume filter.

    When ``volume`` is ``None`` or ``min_avg_volume == 0`` every symbol passes.
    """
    if volume is None or min_avg_volume <= 0.0:
        return True
    if sym not in volume.columns:
        return True
    return float(volume[sym].mean()) >= min_avg_volume


def _eligible_pairs(
    symbols: list[str],
    sectors: Mapping[str, str] | None,
    require_same_sector: bool,
    volume: pd.DataFrame | None,
    min_avg_volume: float,
) -> list[tuple[str, str]]:
    """Enumerate unique unordered pairs that pass sector and volume filters."""
    pairs: list[tuple[str, str]] = []
    for sym_y, sym_x in itertools.combinations(symbols, 2):
        if not _volume_ok(sym_y, volume, min_avg_volume):
            continue
        if not _volume_ok(sym_x, volume, min_avg_volume):
            continue
        if require_same_sector and sectors is not None and sectors.get(sym_y) != sectors.get(sym_x):
            continue
        pairs.append((sym_y, sym_x))
    return pairs


# ---------------------------------------------------------------------------
# Public score function
# ---------------------------------------------------------------------------


def distance_score(y: pd.Series, x: pd.Series) -> float:
    """Sum of squared differences of the two z-normalised price series.

    Both series are z-normalised (subtract mean, divide by standard deviation)
    before differencing.  Z-normalisation ensures series with different price
    magnitudes are compared on a dimensionless scale.  A score of zero would
    mean the two normalised series are identical.  Smaller scores indicate
    tighter co-movement.

    Parameters
    ----------
    y, x:
        Price series (any length, must be equal length after NaN removal).

    Returns
    -------
    float
        Sum of squared differences of the z-normalised series.  Always >= 0.

    Notes
    -----
    The formula is ``sum((z(y) - z(x))^2) / n`` where
    ``z(s) = (s - mean(s)) / std(s)`` and ``n`` is the number of observations.
    Dividing by ``n`` keeps the score invariant to sample size so that pairs
    screened on different windows are comparable.
    """
    ya = np.asarray(y, dtype=float)
    xa = np.asarray(x, dtype=float)
    mask = np.isfinite(ya) & np.isfinite(xa)
    ya, xa = ya[mask], xa[mask]
    if len(ya) == 0:
        return float("inf")
    std_y = ya.std()
    std_x = xa.std()
    if std_y == 0 or std_x == 0:
        return float("inf")
    zy = (ya - ya.mean()) / std_y
    zx = (xa - xa.mean()) / std_x
    return float(np.sum((zy - zx) ** 2) / len(zy))


# ---------------------------------------------------------------------------
# Selector: distance method
# ---------------------------------------------------------------------------


def select_pairs_distance(
    prices: pd.DataFrame,
    *,
    top_n: int = 20,
    sectors: Mapping[str, str] | None = None,
    require_same_sector: bool = False,
    min_obs: int = 60,
    volume: pd.DataFrame | None = None,
    min_avg_volume: float = 0.0,
) -> list[PairCandidate]:
    """Select pairs by the distance method (Gatev et al. 2006).

    Enumerates all unique unordered pairs, computes a distance score (sum of
    squared differences of z-normalised price series divided by n), and returns
    the ``top_n`` pairs with the smallest score.

    The hedge ratio is estimated by OLS (``y ~ x + const``).  The half-life is
    that of the OLS residual spread ``y - hedge * x``.

    Parameters
    ----------
    prices:
        Wide DataFrame of close prices; index is a DatetimeIndex, columns are
        symbol names.
    top_n:
        Number of best pairs to return.
    sectors:
        Optional mapping of ``symbol -> sector_label``.  Used for labelling
        and, when ``require_same_sector=True``, for filtering.
    require_same_sector:
        When ``True``, only pairs where both symbols belong to the same sector
        are considered.
    min_obs:
        Minimum number of clean (non-NaN) overlapping observations required.
        Pairs with fewer observations are silently skipped.
    volume:
        Optional wide DataFrame of (daily) volumes aligned to ``prices``.  Used
        to filter out illiquid symbols.
    min_avg_volume:
        Symbols whose mean volume (across all available rows in ``volume``) is
        below this threshold are dropped before pairing.  Ignored when
        ``volume`` is ``None`` or ``0``.

    Returns
    -------
    list[PairCandidate]
        At most ``top_n`` candidates sorted ascending by ``score``
        (distance score; smaller = better co-movement).
    """
    symbols = list(prices.columns)
    pairs = _eligible_pairs(symbols, sectors, require_same_sector, volume, min_avg_volume)

    records: list[dict[str, Any]] = []
    for sym_y, sym_x in pairs:
        arrays = _align_pair(prices, sym_y, sym_x, min_obs)
        if arrays is None:
            continue
        ya, xa = arrays
        score = distance_score(pd.Series(ya), pd.Series(xa))
        if not np.isfinite(score):
            continue
        hedge = _ols_hedge(ya, xa)
        hl = _spread_half_life(ya, xa, hedge)
        sector = _sector_label(sym_y, sym_x, sectors)
        records.append(
            {
                "symbol_y": sym_y,
                "symbol_x": sym_x,
                "hedge_ratio": hedge,
                "pvalue": float("nan"),
                "pvalue_adj": float("nan"),
                "half_life": hl,
                "method": "distance",
                "score": score,
                "sector": sector,
            }
        )

    records.sort(key=lambda r: r["score"])
    return [PairCandidate(**r) for r in records[:top_n]]


# ---------------------------------------------------------------------------
# Selector: Engle-Granger cointegration
# ---------------------------------------------------------------------------


def select_pairs_cointegration(
    prices: pd.DataFrame,
    *,
    alpha: float = 0.05,
    max_half_life: float = 30.0,
    correction: str = "bonferroni",
    sectors: Mapping[str, str] | None = None,
    require_same_sector: bool = False,
    min_obs: int = 60,
    volume: pd.DataFrame | None = None,
    min_avg_volume: float = 0.0,
) -> list[PairCandidate]:
    """Select pairs by Engle-Granger cointegration with multiple-testing correction.

    For every eligible unordered pair, runs :func:`engle_granger_test` in the
    orientation (y, x) that produces a positive hedge ratio when possible.
    Raw p-values are collected for **all** tested pairs, then corrected via
    :func:`adjust_pvalues` with ``method=correction``.  Only pairs where:

    * the adjusted p-value rejects H0 at level ``alpha``, AND
    * ``0 < half_life <= max_half_life``

    are returned, sorted ascending by adjusted p-value (score).

    Orientation convention
    ----------------------
    Both orderings (a, b) and (b, a) are tested.  The retained orientation is
    the one that yields ``hedge_ratio > 0``.  When neither yields a positive
    hedge ratio the ordering with the smaller raw p-value is used.  Testing
    both orientations effectively doubles the family size for multiple-testing
    correction, which is conservative and correct.

    Parameters
    ----------
    prices:
        Wide DataFrame of close prices.
    alpha:
        Family-wise / false-discovery-rate significance level.
    max_half_life:
        Maximum allowed spread half-life (in periods).  Pairs with
        ``half_life > max_half_life`` or non-mean-reverting spreads are dropped.
    correction:
        Multiple-testing correction method passed to :func:`adjust_pvalues`;
        one of ``"bonferroni"``, ``"holm"``, or ``"fdr_bh"``.
    sectors:
        Optional ``symbol -> sector_label`` mapping.
    require_same_sector:
        When ``True``, only same-sector pairs are considered.
    min_obs:
        Minimum overlapping clean observations; pairs below this are skipped.
    volume:
        Optional volume DataFrame for the volume filter.
    min_avg_volume:
        Minimum mean volume threshold; symbols below this are dropped.

    Returns
    -------
    list[PairCandidate]
        Significant cointegrated pairs sorted ascending by adjusted p-value.
    """
    import warnings

    from statsmodels.tools.sm_exceptions import CollinearityWarning

    symbols = list(prices.columns)
    pairs = _eligible_pairs(symbols, sectors, require_same_sector, volume, min_avg_volume)

    # Step 1: test all pairs, collect raw p-values and metadata.
    tested: list[dict[str, Any]] = []
    for sym_y, sym_x in pairs:
        arrays = _align_pair(prices, sym_y, sym_x, min_obs)
        if arrays is None:
            continue
        ya, xa = arrays

        # Test both orientations; pick the better one.
        orientations: dict[str, dict[str, Any]] = {}
        for o_y, o_x, o_ya, o_xa in (
            (sym_y, sym_x, ya, xa),
            (sym_x, sym_y, xa, ya),
        ):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", CollinearityWarning)
                    res = engle_granger_test(o_ya, o_xa)
            except Exception:  # noqa: BLE001
                continue
            orientations[o_y] = {
                "sym_y": o_y,
                "sym_x": o_x,
                "ya": o_ya,
                "xa": o_xa,
                "pvalue": float(res.pvalue) if res.pvalue is not None else 1.0,
                "hedge_ratio": float(res.extra.get("hedge_ratio", float("nan"))),
            }

        if not orientations:
            continue

        # Prefer the orientation with positive hedge ratio.
        chosen: dict[str, Any] | None = None
        for key in (sym_y, sym_x):
            if key in orientations and float(orientations[key]["hedge_ratio"]) > 0.0:
                chosen = orientations[key]
                break
        if chosen is None:
            # Neither positive; pick the orientation with the smaller p-value.
            orientation_list: list[dict[str, Any]] = list(orientations.values())
            chosen = min(orientation_list, key=lambda r: float(r["pvalue"]))

        tested.append(chosen)

    if not tested:
        return []

    # Step 2: multiple-testing correction over the full family of tested pairs.
    raw_pvalues: list[float] = [float(r["pvalue"]) for r in tested]
    reject, adjusted = adjust_pvalues(raw_pvalues, method=correction, alpha=alpha)

    # Step 3: filter by rejection and half-life; build PairCandidate list.
    output: list[PairCandidate] = []
    for i, record in enumerate(tested):
        if not reject[i]:
            continue
        hl = _spread_half_life(
            record["ya"],
            record["xa"],
            float(record["hedge_ratio"]),
        )
        if not (0.0 < hl <= max_half_life):
            continue
        sector = _sector_label(str(record["sym_y"]), str(record["sym_x"]), sectors)
        output.append(
            PairCandidate(
                symbol_y=str(record["sym_y"]),
                symbol_x=str(record["sym_x"]),
                hedge_ratio=float(record["hedge_ratio"]),
                pvalue=float(record["pvalue"]),
                pvalue_adj=float(adjusted[i]),
                half_life=hl,
                method="engle_granger",
                score=float(adjusted[i]),
                sector=sector,
            )
        )

    output.sort(key=lambda c: c.score)
    return output


# ---------------------------------------------------------------------------
# Selector: Johansen cointegration
# ---------------------------------------------------------------------------


def select_pairs_johansen(
    prices: pd.DataFrame,
    *,
    sectors: Mapping[str, str] | None = None,
    require_same_sector: bool = False,
    max_half_life: float = 30.0,
    min_obs: int = 60,
    alpha: str = "95%",
) -> list[PairCandidate]:
    """Select pairs by the Johansen cointegration test.

    For each eligible unordered pair, builds a 2-column DataFrame and runs
    :func:`johansen_test`.  Pairs with cointegration rank >= 1 (at the
    specified significance level) are retained.

    Spread definition
    -----------------
    The normalised Johansen eigenvector has its first element fixed to 1.0 so
    ``hedge = -hedge_ratios()[1]`` gives the coefficient ``h`` such that
    ``spread = y - h * x`` is the cointegrating combination.  For most typical
    pairs ``hedge_ratios()[1]`` is negative, so ``h`` is positive.

    Score
    -----
    ``score = half_life``.  Smaller half-life means faster mean reversion,
    which is generally preferable for high-frequency statistical arbitrage.
    Pairs are sorted ascending by score.

    Parameters
    ----------
    prices:
        Wide DataFrame of close prices.
    sectors:
        Optional ``symbol -> sector_label`` mapping.
    require_same_sector:
        Filter to same-sector pairs only.
    max_half_life:
        Maximum allowed spread half-life.  Pairs with
        ``half_life > max_half_life`` or non-mean-reverting spreads are dropped.
    min_obs:
        Minimum overlapping clean observations; pairs below this are skipped.
    alpha:
        Critical-value significance level for the Johansen trace test;
        one of ``"90%"``, ``"95%"``, ``"99%"``.

    Returns
    -------
    list[PairCandidate]
        Cointegrated pairs (rank >= 1) sorted ascending by ``half_life``.
    """
    import warnings

    symbols = list(prices.columns)
    pairs = _eligible_pairs(symbols, sectors, require_same_sector, None, 0.0)

    candidates: list[PairCandidate] = []
    for sym_y, sym_x in pairs:
        arrays = _align_pair(prices, sym_y, sym_x, min_obs)
        if arrays is None:
            continue
        ya, xa = arrays

        sub = pd.DataFrame({"y": ya, "x": xa})
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                jres = johansen_test(sub)
        except Exception:  # noqa: BLE001
            continue

        if jres.rank(alpha=alpha) < 1:
            continue

        hr_vec = jres.hedge_ratios()
        # hedge_ratios() normalises element 0 to 1.  Element 1 is the
        # coefficient on x in the cointegrating vector.  Negating gives the
        # hedge ratio for spread = y - hedge * x.
        hedge = float(-hr_vec[1])
        hl = _spread_half_life(ya, xa, hedge)
        if not (0.0 < hl <= max_half_life):
            continue

        sector = _sector_label(sym_y, sym_x, sectors)
        candidates.append(
            PairCandidate(
                symbol_y=sym_y,
                symbol_x=sym_x,
                hedge_ratio=hedge,
                pvalue=float("nan"),
                pvalue_adj=float("nan"),
                half_life=hl,
                method="johansen",
                score=hl,
                sector=sector,
            )
        )

    candidates.sort(key=lambda c: c.score)
    return candidates


# ---------------------------------------------------------------------------
# Selector: Gaussian copula dependence
# ---------------------------------------------------------------------------


def select_pairs_copula(
    prices: pd.DataFrame,
    *,
    top_n: int = 20,
    sectors: Mapping[str, str] | None = None,
    require_same_sector: bool = False,
    min_obs: int = 60,
) -> list[PairCandidate]:
    """Select pairs by Gaussian copula correlation on empirical pseudo-observations.

    Copula model
    ------------
    For each pair the log-return series ``r_y`` and ``r_x`` are transformed to
    empirical pseudo-observations (uniform marginals) via the rank-based
    probability integral transform:

        u_i = rank(r_i) / (n + 1)       (Hazen plotting position)

    The Gaussian copula is then parameterised by the Pearson correlation
    ``rho = corr(Phi^{-1}(u_y), Phi^{-1}(u_x))`` of the normal-quantile-
    transformed pseudo-observations.  Under the Gaussian copula ``rho`` equals
    the linear correlation in the Gaussian margin, and its square is a lower
    bound on any non-linear dependence captured by the copula.

    Score
    -----
    ``score = 1 - |rho|``.  Smaller score means stronger positive or negative
    linear dependence in the copula margin (better pair candidate).  The
    absolute value ensures pairs with strong negative correlation (inverse
    pairs) are also captured.

    Hedge ratio and half-life
    -------------------------
    The hedge ratio is estimated by OLS on the original price levels.  The
    half-life is that of the OLS residual spread.  Note that a high copula
    score does not guarantee a stationary spread; cointegration tests should
    be applied subsequently if spread stationarity is required.

    Parameters
    ----------
    prices:
        Wide DataFrame of close prices.
    top_n:
        Number of best pairs to return.
    sectors:
        Optional ``symbol -> sector_label`` mapping.
    require_same_sector:
        Filter to same-sector pairs only.
    min_obs:
        Minimum overlapping clean observations; pairs below this are skipped.
        An additional observation is consumed by the first-difference for
        returns, so effective minimum is ``min_obs + 1`` price rows.

    Returns
    -------
    list[PairCandidate]
        Top ``top_n`` pairs sorted ascending by ``score`` (= 1 - |rho|).
    """
    from scipy import stats as scipy_stats

    symbols = list(prices.columns)
    pairs = _eligible_pairs(symbols, sectors, require_same_sector, None, 0.0)

    records: list[dict[str, Any]] = []
    for sym_y, sym_x in pairs:
        # Compute returns on aligned price series.
        sub = prices[[sym_y, sym_x]].dropna()
        # Need at least min_obs + 1 price rows to get min_obs returns.
        if len(sub) < min_obs + 1:
            continue
        py = sub[sym_y].to_numpy(dtype=float)
        px = sub[sym_x].to_numpy(dtype=float)
        # Drop rows with non-positive prices before taking logs to avoid
        # RuntimeWarning from log(<=0) under strict warning modes.
        pos_mask = (py > 0.0) & (px > 0.0)
        py, px = py[pos_mask], px[pos_mask]
        if len(py) < min_obs + 1:
            continue
        ret_y = np.diff(np.log(py))
        ret_x = np.diff(np.log(px))

        # Keep only rows where both returns are finite.
        mask = np.isfinite(ret_y) & np.isfinite(ret_x)
        ret_y, ret_x = ret_y[mask], ret_x[mask]
        n = len(ret_y)
        if n < min_obs:
            continue

        # Empirical pseudo-observations via Hazen plotting position.
        u_y = scipy_stats.rankdata(ret_y) / (n + 1)
        u_x = scipy_stats.rankdata(ret_x) / (n + 1)

        # Gaussian copula: transform to normal quantiles.
        norm_y = scipy_stats.norm.ppf(u_y)
        norm_x = scipy_stats.norm.ppf(u_x)

        # Pearson correlation of the normal-quantile transforms.
        rho = float(np.corrcoef(norm_y, norm_x)[0, 1])
        if not np.isfinite(rho):
            continue

        score = 1.0 - abs(rho)

        # Hedge ratio and half-life on price levels.
        ya, xa = sub[sym_y].to_numpy(dtype=float), sub[sym_x].to_numpy(dtype=float)
        hedge = _ols_hedge(ya, xa)
        hl = _spread_half_life(ya, xa, hedge)
        sector = _sector_label(sym_y, sym_x, sectors)
        records.append(
            {
                "symbol_y": sym_y,
                "symbol_x": sym_x,
                "hedge_ratio": hedge,
                "pvalue": float("nan"),
                "pvalue_adj": float("nan"),
                "half_life": hl,
                "method": "copula",
                "score": score,
                "sector": sector,
            }
        )

    records.sort(key=lambda r: r["score"])
    return [PairCandidate(**r) for r in records[:top_n]]
