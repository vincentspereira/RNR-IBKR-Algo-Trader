"""Data quality framework.

Per master plan Phase 1.8: free data is fine *if* you actively validate it.
This module implements the validation primitives that every adapter pipeline
runs against fetched data, plus a small report object that the data-quality
dashboard consumes.

The validators here are vendor-agnostic. Vendor-specific quirks (e.g. Yahoo
returning a single 0.0 close on holiday boundaries) are handled inside the
adapter; this layer catches the structural problems that nobody is allowed
to ship to a backtest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(slots=True)
class QualityIssue:
    """One specific problem found in a bar frame."""

    severity: str
    category: str
    symbol: str | None
    detail: str

    def __post_init__(self) -> None:
        if self.severity not in {"info", "warn", "error"}:
            raise ValueError(f"Unknown severity {self.severity!r}")


@dataclass(slots=True)
class QualityReport:
    """Aggregated result of validating a fetched bar frame."""

    source: str
    n_rows: int
    n_symbols: int
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warn" for i in self.issues)

    def summary(self) -> str:
        counts = {"info": 0, "warn": 0, "error": 0}
        for i in self.issues:
            counts[i.severity] += 1
        return (
            f"[quality] {self.source}: {self.n_rows} rows x {self.n_symbols} symbols, "
            f"{counts['error']} errors, {counts['warn']} warnings, {counts['info']} info"
        )


def validate_bar_frame(
    df: pd.DataFrame,
    source: str,
    *,
    expected_resolution_seconds: int | None = None,
    spike_z_threshold: float = 10.0,
) -> QualityReport:
    """Run the standard quality checks against a bar frame.

    Checks (per master plan Phase 1.8):
    * structural columns and index shape
    * negative volume
    * high < low
    * duplicate (symbol, timestamp) rows
    * single-symbol price gaps larger than ``spike_z_threshold`` standard deviations
    * timestamp gaps significantly larger than ``expected_resolution_seconds``
    * all-zero or all-NaN close columns per symbol
    """
    n_symbols = df.index.get_level_values("symbol").nunique() if not df.empty else 0
    report = QualityReport(source=source, n_rows=len(df), n_symbols=n_symbols)

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        report.issues.append(
            QualityIssue(
                severity="error",
                category="schema",
                symbol=None,
                detail=f"missing required columns: {sorted(missing)}",
            )
        )
        return report

    if df.empty:
        report.issues.append(
            QualityIssue("warn", "empty", None, "no rows in fetched frame")
        )
        return report

    if df["volume"].lt(0).any():
        n = int(df["volume"].lt(0).sum())
        report.issues.append(
            QualityIssue("error", "negative_volume", None, f"{n} rows with negative volume")
        )

    inverted = df["high"] < df["low"]
    if inverted.any():
        report.issues.append(
            QualityIssue(
                "error",
                "high_lt_low",
                None,
                f"{int(inverted.sum())} rows with high < low",
            )
        )

    dup_mask = df.index.duplicated(keep=False)
    if dup_mask.any():
        report.issues.append(
            QualityIssue(
                "error",
                "duplicate_rows",
                None,
                f"{int(dup_mask.sum())} duplicate (symbol, timestamp) rows",
            )
        )

    for symbol in df.index.get_level_values("symbol").unique():
        sub = df.xs(symbol, level="symbol")
        closes = sub["close"].dropna()
        if closes.empty:
            report.issues.append(
                QualityIssue("warn", "all_nan_close", symbol, "all close values are NaN")
            )
            continue

        if (closes == 0).all():
            report.issues.append(
                QualityIssue("error", "all_zero_close", symbol, "all close values are zero")
            )
            continue

        rets = closes.pct_change().dropna()
        if not rets.empty:
            sigma = rets.std()
            if sigma > 0:
                z = (rets - rets.mean()).abs() / sigma
                spikes = z[z > spike_z_threshold]
                if len(spikes) > 0:
                    report.issues.append(
                        QualityIssue(
                            "warn",
                            "price_spike",
                            symbol,
                            f"{len(spikes)} returns exceed {spike_z_threshold} sigma",
                        )
                    )

        if expected_resolution_seconds is not None and len(sub.index) > 1:
            deltas = np.diff(sub.index.values).astype("timedelta64[s]").astype(int)
            expected = expected_resolution_seconds
            big_gaps = (deltas > expected * 3).sum()
            if big_gaps > 0:
                report.issues.append(
                    QualityIssue(
                        "info",
                        "time_gap",
                        symbol,
                        f"{int(big_gaps)} timestamp gaps > 3x expected resolution",
                    )
                )

    return report


def cross_source_compare(
    primary: pd.DataFrame,
    secondary: pd.DataFrame,
    *,
    tolerance_bps: float = 5.0,
) -> QualityReport:
    """Compare close-price agreement between two sources.

    Aligns on the intersection of ``(symbol, timestamp)`` and flags any cell
    where the close difference exceeds ``tolerance_bps`` basis points relative
    to the primary value. Used in the data-quality dashboard to catch silent
    yfinance / IBKR divergence.
    """
    p_source = (
        primary["source"].dropna().unique()[0]
        if "source" in primary.columns and not primary["source"].dropna().empty
        else "primary"
    )
    s_source = (
        secondary["source"].dropna().unique()[0]
        if "source" in secondary.columns and not secondary["source"].dropna().empty
        else "secondary"
    )

    aligned = primary["close"].align(secondary["close"], join="inner")
    p_close, s_close = aligned
    report = QualityReport(
        source=f"{p_source}-vs-{s_source}",
        n_rows=len(p_close),
        n_symbols=p_close.index.get_level_values("symbol").nunique() if len(p_close) else 0,
    )
    if p_close.empty:
        report.issues.append(QualityIssue("warn", "no_overlap", None, "no overlapping (symbol, timestamp) rows"))
        return report

    diff_bps = ((s_close - p_close).abs() / p_close.replace(0, np.nan)) * 1e4
    bad = diff_bps[diff_bps > tolerance_bps].dropna()
    if not bad.empty:
        for symbol in bad.index.get_level_values("symbol").unique():
            n = int((bad.index.get_level_values("symbol") == symbol).sum())
            report.issues.append(
                QualityIssue(
                    "warn",
                    "cross_source_disagreement",
                    symbol,
                    f"{n} bars differ by more than {tolerance_bps} bps",
                )
            )
    return report
