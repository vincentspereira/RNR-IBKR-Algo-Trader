"""Pairs-trading portfolio constructor (master plan Phase 4.5).

Translates a set of qualified pair allocations into per-symbol target weights
by applying, in order:

1. Inverse-spread-variance weighting across pairs.
2. Per-pair gross-weight cap.
3. Leg expansion: each pair becomes a long leg in ``symbol_y`` and a short leg
   in ``symbol_x`` (magnitudes scaled by the hedge ratio).
4. Sector-exposure cap: any sector whose gross weight exceeds ``sector_cap``
   of total gross is scaled down proportionally.
5. Gross-leverage cap: if the summed absolute weights still exceed
   ``gross_leverage_cap``, all weights are scaled proportionally.
6. Optional market-beta neutralisation: a hedge position in ``hedge_symbol``
   (default ``"SPY"``) is added to zero out portfolio beta.

Math notes
----------
* Spread definition: S_t = y_t - beta * x_t, where ``beta`` is the hedge ratio.
  Direction +1 means the spread is **long** (buy ``y``, sell ``x``).
* Inverse-variance weight for pair i:  w_i = (1 / sigma_i^2) / sum_j(1 / sigma_j^2),
  summed only over pairs with ``direction != 0`` and ``spread_var > 0``.
* Sector down-scale: for a breaching sector S,
  scale_factor = (sector_cap * total_gross) / sector_gross_S.
  Applied symbol-by-symbol within the sector.
* Beta hedge: hedge_weight = -sum_i(weight_i * beta_i) for i in all symbols
  except the hedge symbol itself.  After adding the hedge,
  net_beta = sum_i(weight_i * beta_i) + hedge_weight * beta_hedge ~ 0.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

__all__ = [
    "PairAllocation",
    "PortfolioConfig",
    "PortfolioWeights",
    "inverse_variance_weights",
    "construct_pairs_portfolio",
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairAllocation:
    """Specification for a single qualified cointegrated pair.

    Attributes
    ----------
    pair_id:
        Unique identifier for the pair (e.g. ``"AAPL_MSFT"``).
    symbol_y:
        The dependent-variable leg (y in y = beta * x + epsilon).
    symbol_x:
        The independent-variable leg (x).
    hedge_ratio:
        Regression coefficient beta; the spread is ``y - beta * x``.
        Must be finite.
    direction:
        Trade direction: ``+1`` = long spread (long y, short x);
        ``-1`` = short spread (short y, long x); ``0`` = flat / no trade.
    spread_var:
        Variance of the pair's spread *returns* over the calibration window.
        Used for inverse-variance weighting; a value ``<= 0`` causes the pair
        to receive zero allocation.
    sector:
        Optional common sector label for both legs (used for sector-cap
        enforcement).  If ``None`` the pair's symbols are treated as having
        no sector affiliation.
    """

    pair_id: str
    symbol_y: str
    symbol_x: str
    hedge_ratio: float
    direction: int
    spread_var: float
    sector: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioConfig:
    """Tuning knobs for :func:`construct_pairs_portfolio`.

    Attributes
    ----------
    gross_leverage_cap:
        Maximum allowed sum of absolute weights (fraction of NAV).
        Must be strictly positive.  Default 2.0 (dollar-neutral pairs
        strategy running at 2x gross leverage).
    sector_cap:
        Maximum fraction of total gross that any single sector may contribute.
        E.g. 0.30 means no sector can account for more than 30 % of gross.
        Must be in (0, 1].
    per_pair_cap:
        Maximum gross weight (as fraction of NAV) that a single pair may
        contribute *before* leg expansion.  Caps the raw inverse-variance
        weight per pair.  Must be in (0, 1].
    beta_neutralize:
        When ``True`` and ``market_betas`` is supplied to
        :func:`construct_pairs_portfolio`, a position in ``hedge_symbol`` is
        added to zero out portfolio beta.
    hedge_symbol:
        Ticker used for the market-beta hedge (default ``"SPY"``).
    """

    gross_leverage_cap: float = 2.0
    sector_cap: float = 0.30
    per_pair_cap: float = 0.02
    beta_neutralize: bool = True
    hedge_symbol: str = "SPY"

    def __post_init__(self) -> None:
        if self.gross_leverage_cap <= 0:
            raise ValueError(
                f"gross_leverage_cap must be > 0; got {self.gross_leverage_cap}"
            )
        if not (0 < self.sector_cap <= 1):
            raise ValueError(
                f"sector_cap must be in (0, 1]; got {self.sector_cap}"
            )
        if not (0 < self.per_pair_cap <= 1):
            raise ValueError(
                f"per_pair_cap must be in (0, 1]; got {self.per_pair_cap}"
            )


@dataclass(frozen=True, slots=True)
class PortfolioWeights:
    """Output of :func:`construct_pairs_portfolio`.

    Attributes
    ----------
    weights:
        Mapping of ``symbol -> signed target weight`` (fraction of NAV).
        A positive weight is a long position; negative is short.
        If beta neutralisation is enabled, the ``hedge_symbol`` will appear
        here with a weight designed to zero out portfolio beta.
    gross_leverage:
        Sum of absolute weights across all symbols *excluding* the hedge
        symbol added by beta neutralisation.  This is the gross leverage
        attributable to the pairs positions themselves.
    net_beta:
        Portfolio beta after beta neutralisation.  Should be approximately
        zero when ``beta_neutralize=True`` and ``market_betas`` is provided.
        Computed as ``sum_i(weight_i * beta_i)`` over all symbols including
        the hedge (whose beta is assumed to be 1.0 unless overridden in
        ``market_betas``).
    sector_exposure:
        Mapping of ``sector -> gross fraction`` (i.e. sector gross / total
        gross of *pairs* positions, excluding the hedge symbol).
    """

    weights: dict[str, float]
    gross_leverage: float
    net_beta: float
    sector_exposure: dict[str, float]


# ---------------------------------------------------------------------------
# Module-level default config singleton (avoids mutable call default -- B008)
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: Final[PortfolioConfig] = PortfolioConfig()


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def inverse_variance_weights(
    allocations: Sequence[PairAllocation],
) -> dict[str, float]:
    """Compute inverse-spread-variance weights, normalised to sum to 1.

    Only pairs with ``direction != 0`` and ``spread_var > 0`` receive a
    non-zero weight.  All others are returned as 0.0.

    The weight for eligible pair i is:

        w_i = (1 / sigma_i^2) / sum_j (1 / sigma_j^2)

    where the sum runs over the eligible subset.

    Parameters
    ----------
    allocations:
        Sequence of :class:`PairAllocation` objects.

    Returns
    -------
    dict[str, float]
        Mapping of ``pair_id -> weight``.  Sums to 1.0 over eligible pairs
        (or 0.0 when no eligible pair exists).
    """
    result: dict[str, float] = {a.pair_id: 0.0 for a in allocations}

    eligible = [a for a in allocations if a.direction != 0 and a.spread_var > 0]
    if not eligible:
        return result

    inv_vars = np.array([1.0 / a.spread_var for a in eligible], dtype=float)
    total = float(inv_vars.sum())
    for alloc, iv in zip(eligible, inv_vars, strict=True):
        result[alloc.pair_id] = float(iv / total)

    return result


def construct_pairs_portfolio(
    allocations: Sequence[PairAllocation],
    *,
    config: PortfolioConfig = _DEFAULT_CONFIG,
    market_betas: Mapping[str, float] | None = None,
) -> PortfolioWeights:
    """Build per-symbol target weights from a list of pair allocations.

    Algorithm (executed in order):

    1. **Inverse-variance weighting**: compute raw pair magnitudes via
       :func:`inverse_variance_weights`.
    2. **Per-pair cap**: clip each pair magnitude to ``config.per_pair_cap``.
       Re-normalise is *not* applied after capping; the remaining slack
       is simply left unallocated (conservative).
    3. **Leg expansion**: for pair weight w_i (>= 0) and direction d_i:

       * ``symbol_y`` leg: ``+d_i * w_i``
       * ``symbol_x`` leg: ``-d_i * w_i * hedge_ratio``

       Contributions from multiple pairs sharing a symbol are summed.
    4. **Sector-cap enforcement**: each round, snapshot ``total_gross``, then
       simultaneously compute a scale factor for every breaching sector:
       ``scale_s = (sector_cap * total_gross) / sector_gross_s``.
       All scale factors are applied in one pass.  The round repeats until no
       sector exceeds the cap (convergence is guaranteed because each round
       strictly reduces gross).
    5. **Gross-leverage cap**: if ``sum |w_i|`` exceeds
       ``config.gross_leverage_cap``, scale all weights proportionally so
       the total equals the cap.
    6. **Beta neutralisation** (optional): if ``config.beta_neutralize`` and
       ``market_betas`` is provided, add a hedge position:

          hedge_weight = -sum_i( w_i * beta_i )   (i != hedge_symbol)

       The hedge symbol is assumed to have beta 1.0 unless its ticker appears
       in ``market_betas``.

    Parameters
    ----------
    allocations:
        Qualified pair specifications.  May be empty.
    config:
        Portfolio construction parameters.  Defaults to the module-level
        :data:`_DEFAULT_CONFIG` singleton.
    market_betas:
        Optional mapping of ``symbol -> market beta``.  Required for beta
        neutralisation; ignored when ``config.beta_neutralize`` is ``False``
        or this argument is ``None``.

    Returns
    -------
    PortfolioWeights
        Per-symbol signed weights, gross leverage, net beta, and sector
        exposures.  The ``gross_leverage`` field excludes the hedge symbol.
    """
    # ------------------------------------------------------------------ #
    # Edge case: no allocations
    # ------------------------------------------------------------------ #
    if not allocations:
        return PortfolioWeights(
            weights={},
            gross_leverage=0.0,
            net_beta=0.0,
            sector_exposure={},
        )

    # ------------------------------------------------------------------ #
    # Step 1: inverse-variance weights (pair magnitudes)
    # ------------------------------------------------------------------ #
    pair_weights = inverse_variance_weights(allocations)

    # ------------------------------------------------------------------ #
    # Step 2: per-pair cap (clip, no re-normalisation)
    # ------------------------------------------------------------------ #
    for pid in pair_weights:
        if pair_weights[pid] > config.per_pair_cap:
            pair_weights[pid] = config.per_pair_cap

    # ------------------------------------------------------------------ #
    # Step 3: leg expansion -> per-symbol weights
    # ------------------------------------------------------------------ #
    # Build an index for quick lookup of sector per symbol
    symbol_sector: dict[str, str | None] = {}
    symbol_weights: dict[str, float] = {}

    for alloc in allocations:
        w = pair_weights[alloc.pair_id]
        if w == 0.0 or alloc.direction == 0:
            continue

        d = float(alloc.direction)
        y_delta = d * w
        x_delta = -d * w * alloc.hedge_ratio

        symbol_weights[alloc.symbol_y] = symbol_weights.get(alloc.symbol_y, 0.0) + y_delta
        symbol_weights[alloc.symbol_x] = symbol_weights.get(alloc.symbol_x, 0.0) + x_delta

        # Sector registration: last-write wins for consistency within a pair.
        if alloc.sector is not None:
            symbol_sector[alloc.symbol_y] = alloc.sector
            symbol_sector[alloc.symbol_x] = alloc.sector
        else:
            symbol_sector.setdefault(alloc.symbol_y, None)
            symbol_sector.setdefault(alloc.symbol_x, None)

    # ------------------------------------------------------------------ #
    # Step 4: sector-cap enforcement
    # ------------------------------------------------------------------ #
    # Group symbols by sector (skip None)
    sector_symbols: dict[str, list[str]] = {}
    for sym, sec in symbol_sector.items():
        if sec is not None:
            sector_symbols.setdefault(sec, []).append(sym)

    # Round-based simultaneous scale using the correct closed-form factor.
    #
    # For a sector with gross ``s`` and everything else ``r = total - s``,
    # the scale factor that brings the sector exactly to the cap ``c`` is:
    #
    #     f = c * r / (s * (1 - c))
    #
    # Derivation: we want ``s*f / (s*f + r) = c``, which gives
    # ``f = c*r / (s*(1-c))``.
    #
    # All breaching sectors are scaled simultaneously using a snapshot of
    # total_gross taken at the start of each round.  Rounds repeat until no
    # sector exceeds the cap (convergence guaranteed; each round reduces gross).
    c = config.sector_cap
    for _ in range(32):  # safety limit; well above any realistic sector count
        total_gross = sum(abs(v) for v in symbol_weights.values())
        if total_gross == 0.0:
            break
        # Compute per-sector scale factors
        sector_scales: dict[str, float] = {}
        any_breach = False
        for sec, syms in sector_symbols.items():
            sec_gross = sum(abs(symbol_weights.get(s, 0.0)) for s in syms)
            if sec_gross > c * total_gross + 1e-12:
                rest_gross = total_gross - sec_gross
                # c < 1 always (validated in __post_init__); guard for safety
                sector_scales[sec] = (c * rest_gross) / (sec_gross * (1.0 - c))
                any_breach = True
            else:
                sector_scales[sec] = 1.0
        if not any_breach:
            break
        # Apply all scale factors simultaneously
        for sec, syms in sector_symbols.items():
            sf = sector_scales[sec]
            if sf < 1.0:
                for sym in syms:
                    if sym in symbol_weights:
                        symbol_weights[sym] = symbol_weights[sym] * sf

    # ------------------------------------------------------------------ #
    # Step 5: gross-leverage cap
    # ------------------------------------------------------------------ #
    total_gross = sum(abs(v) for v in symbol_weights.values())
    if total_gross > config.gross_leverage_cap and total_gross > 0.0:
        scale = config.gross_leverage_cap / total_gross
        for sym in symbol_weights:
            symbol_weights[sym] = symbol_weights[sym] * scale

    # Capture gross leverage BEFORE adding the hedge symbol
    pairs_gross = sum(abs(v) for v in symbol_weights.values())

    # ------------------------------------------------------------------ #
    # Step 6: beta neutralisation
    # ------------------------------------------------------------------ #
    hedge_sym = config.hedge_symbol
    if config.beta_neutralize and market_betas is not None:
        # Sum portfolio beta over pairs positions only (exclude hedge_sym)
        portfolio_beta = sum(
            symbol_weights.get(sym, 0.0) * market_betas.get(sym, 0.0)
            for sym in symbol_weights
            if sym != hedge_sym
        )
        hedge_weight = -portfolio_beta
        # Accumulate with any existing hedge-symbol position (rare but safe)
        symbol_weights[hedge_sym] = symbol_weights.get(hedge_sym, 0.0) + hedge_weight

    # ------------------------------------------------------------------ #
    # Compute output metrics
    # ------------------------------------------------------------------ #
    # Net beta: sum over ALL symbols; hedge_sym assumed beta=1.0 unless given
    if market_betas is not None:
        net_beta = sum(
            w * (market_betas[sym] if sym != hedge_sym else market_betas.get(sym, 1.0))
            for sym, w in symbol_weights.items()
        )
    else:
        net_beta = 0.0

    # Sector exposure (as fraction of pairs gross, excluding hedge symbol)
    sector_exposure: dict[str, float] = {}
    if pairs_gross > 0.0:
        for sec, syms in sector_symbols.items():
            sec_gross = sum(
                abs(symbol_weights.get(s, 0.0)) for s in syms if s != hedge_sym
            )
            sector_exposure[sec] = sec_gross / pairs_gross

    return PortfolioWeights(
        weights=symbol_weights,
        gross_leverage=pairs_gross,
        net_beta=float(net_beta),
        sector_exposure=sector_exposure,
    )
