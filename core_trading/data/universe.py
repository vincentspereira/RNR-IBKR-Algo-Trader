"""Universe construction.

Defines :class:`Universe` and :class:`UniverseMembership`. A universe is the
investable set of symbols at a given point in time. Survivorship-bias-free
universes track membership changes over time and include delisted names.

Per the master plan Phase 1.1: a survivorship-bias-aware universe API does
*not* mean we have institutional-grade vintage data on day one. It means the
**interface** distinguishes "current membership" from "historical membership
on a specific date", so as we acquire vintage data (Tiingo free tier for some
US tickers; Norgate paid for full coverage), the call sites do not change.

Built-in universes ship as static snapshots dated 2026-05-28 and clearly marked
as such. Code paths that need vintage data ask the universe by date; if no
vintage record exists, the static snapshot is returned with
``is_vintage=False`` so the caller knows the membership is approximate.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime


@dataclass(frozen=True, slots=True)
class UniverseMembership:
    """Membership record for one symbol over a date range."""

    symbol: str
    added: date
    removed: date | None = None

    def is_member_on(self, as_of: date) -> bool:
        if as_of < self.added:
            return False
        return not (self.removed is not None and as_of >= self.removed)


@dataclass(slots=True)
class Universe:
    """A named set of symbols with optional time-aware membership tracking."""

    name: str
    description: str
    snapshot_date: date
    is_vintage: bool
    memberships: tuple[UniverseMembership, ...] = field(default_factory=tuple)

    def current_symbols(self) -> tuple[str, ...]:
        """Return the symbol set as of :attr:`snapshot_date`."""
        return self.members_on(self.snapshot_date)

    def members_on(self, as_of: date) -> tuple[str, ...]:
        """Return the symbol set that was a member on ``as_of``.

        If ``is_vintage`` is ``False`` the membership records are a single
        static snapshot; this method then returns the snapshot for any
        ``as_of`` after the snapshot date and an empty tuple for earlier
        dates. The caller should check :attr:`is_vintage` if vintage
        correctness matters.
        """
        if not self.is_vintage:
            if as_of < self.snapshot_date:
                return ()
            return tuple(sorted(m.symbol for m in self.memberships))
        return tuple(sorted(m.symbol for m in self.memberships if m.is_member_on(as_of)))

    def __contains__(self, symbol: str) -> bool:
        return any(m.symbol == symbol for m in self.memberships)


def _snapshot(name: str, description: str, symbols: Iterable[str]) -> Universe:
    """Helper: build a static (non-vintage) universe snapshot dated 2026-05-28."""
    snap = date(2026, 5, 28)
    memberships = tuple(UniverseMembership(symbol=s, added=snap) for s in sorted(set(symbols)))
    return Universe(
        name=name,
        description=description,
        snapshot_date=snap,
        is_vintage=False,
        memberships=memberships,
    )


# ---------------------------------------------------------------------------
# Built-in universes
# ---------------------------------------------------------------------------

# S&P 100 -- large-cap US equities, good starter universe for pairs trading
# and factor research. Source: official S&P index list 2026-05.
_SP100_SYMBOLS = (
    "AAPL",
    "ABBV",
    "ABT",
    "ACN",
    "ADBE",
    "AIG",
    "AMD",
    "AMGN",
    "AMT",
    "AMZN",
    "AVGO",
    "AXP",
    "BA",
    "BAC",
    "BK",
    "BLK",
    "BMY",
    "BRK-B",
    "C",
    "CAT",
    "CHTR",
    "CL",
    "CMCSA",
    "COF",
    "COP",
    "COST",
    "CRM",
    "CSCO",
    "CVS",
    "CVX",
    "DE",
    "DHR",
    "DIS",
    "DOW",
    "DUK",
    "EMR",
    "EXC",
    "F",
    "FDX",
    "GD",
    "GE",
    "GILD",
    "GM",
    "GOOG",
    "GOOGL",
    "GS",
    "HD",
    "HON",
    "IBM",
    "INTC",
    "JNJ",
    "JPM",
    "KHC",
    "KO",
    "LIN",
    "LLY",
    "LMT",
    "LOW",
    "MA",
    "MCD",
    "MDLZ",
    "MDT",
    "MET",
    "META",
    "MMM",
    "MO",
    "MRK",
    "MS",
    "MSFT",
    "NEE",
    "NFLX",
    "NKE",
    "NVDA",
    "ORCL",
    "PEP",
    "PFE",
    "PG",
    "PM",
    "PYPL",
    "QCOM",
    "RTX",
    "SBUX",
    "SCHW",
    "SO",
    "SPG",
    "T",
    "TGT",
    "TMO",
    "TMUS",
    "TSLA",
    "TXN",
    "UNH",
    "UNP",
    "UPS",
    "USB",
    "V",
    "VZ",
    "WBA",
    "WFC",
    "WMT",
    "XOM",
)

# NASDAQ 100 -- tech-heavy large caps, used for momentum and growth strategies.
_NDX_SYMBOLS = (
    "AAPL",
    "ABNB",
    "ADBE",
    "ADI",
    "ADP",
    "ADSK",
    "AEP",
    "AMAT",
    "AMD",
    "AMGN",
    "AMZN",
    "ANSS",
    "ASML",
    "AVGO",
    "AZN",
    "BIIB",
    "BKNG",
    "BKR",
    "CCEP",
    "CDNS",
    "CDW",
    "CEG",
    "CHTR",
    "CMCSA",
    "COST",
    "CPRT",
    "CRWD",
    "CSCO",
    "CSGP",
    "CSX",
    "CTAS",
    "CTSH",
    "DASH",
    "DDOG",
    "DLTR",
    "DXCM",
    "EA",
    "EXC",
    "FANG",
    "FAST",
    "FTNT",
    "GEHC",
    "GFS",
    "GILD",
    "GOOG",
    "GOOGL",
    "HON",
    "IDXX",
    "ILMN",
    "INTC",
    "INTU",
    "ISRG",
    "KDP",
    "KHC",
    "KLAC",
    "LIN",
    "LRCX",
    "LULU",
    "MAR",
    "MCHP",
    "MDB",
    "MDLZ",
    "MELI",
    "META",
    "MNST",
    "MRNA",
    "MRVL",
    "MSFT",
    "MU",
    "NFLX",
    "NVDA",
    "NXPI",
    "ODFL",
    "ON",
    "ORLY",
    "PANW",
    "PAYX",
    "PCAR",
    "PDD",
    "PEP",
    "PYPL",
    "QCOM",
    "REGN",
    "ROP",
    "ROST",
    "SBUX",
    "SMCI",
    "SNPS",
    "TEAM",
    "TMUS",
    "TSLA",
    "TTD",
    "TXN",
    "VRSK",
    "VRTX",
    "WBD",
    "WDAY",
    "XEL",
    "ZS",
)

# NIFTY 50 -- top Indian large caps, NSE-listed (suffix ".NS" for yfinance).
_NIFTY50_SYMBOLS = (
    "ADANIENT.NS",
    "ADANIPORTS.NS",
    "APOLLOHOSP.NS",
    "ASIANPAINT.NS",
    "AXISBANK.NS",
    "BAJAJ-AUTO.NS",
    "BAJAJFINSV.NS",
    "BAJFINANCE.NS",
    "BEL.NS",
    "BHARTIARTL.NS",
    "BPCL.NS",
    "BRITANNIA.NS",
    "CIPLA.NS",
    "COALINDIA.NS",
    "DRREDDY.NS",
    "EICHERMOT.NS",
    "GRASIM.NS",
    "HCLTECH.NS",
    "HDFCBANK.NS",
    "HDFCLIFE.NS",
    "HEROMOTOCO.NS",
    "HINDALCO.NS",
    "HINDUNILVR.NS",
    "ICICIBANK.NS",
    "INDUSINDBK.NS",
    "INFY.NS",
    "ITC.NS",
    "JSWSTEEL.NS",
    "KOTAKBANK.NS",
    "LT.NS",
    "M&M.NS",
    "MARUTI.NS",
    "NESTLEIND.NS",
    "NTPC.NS",
    "ONGC.NS",
    "POWERGRID.NS",
    "RELIANCE.NS",
    "SBILIFE.NS",
    "SBIN.NS",
    "SHRIRAMFIN.NS",
    "SUNPHARMA.NS",
    "TATACONSUM.NS",
    "TATAMOTORS.NS",
    "TATASTEEL.NS",
    "TCS.NS",
    "TECHM.NS",
    "TITAN.NS",
    "TRENT.NS",
    "ULTRACEMCO.NS",
    "WIPRO.NS",
)


# Core liquid US-listed ETFs with long histories (most launched 1993-2007).
# Used as a survivorship-robust cross-validation universe: an index/sector
# ETF cannot go to zero via single-name bankruptcy, and closing ETFs
# liquidate at NAV rather than at a distressed price, so the dip-buying
# survivorship mechanism that flatters single-stock backtests is structurally
# absent. (The list itself is a present-day selection, so treat results as
# survivorship-ROBUST, not survivorship-proof.)
_ETF_CORE_SYMBOLS = (
    # broad US equity
    "SPY", "QQQ", "DIA", "IWM", "MDY", "IJR", "RSP", "VTI",
    # S&P sector SPDRs (1998)
    "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY",
    # industries
    "SMH", "IBB", "XBI", "XHB", "XRT", "KRE", "GDX", "IYR", "IYT", "ITB", "OIH",
    # international single-country / regional
    "EFA", "EEM", "EWJ", "EWG", "EWU", "EWC", "EWA", "EWH", "EWS",
    "EWY", "EWT", "EWZ", "EWW", "FXI", "ILF", "EPP",
    # bonds
    "TLT", "IEF", "SHY", "LQD", "AGG", "TIP", "HYG",
    # commodities
    "GLD", "SLV", "USO", "DBC",
)


SP100 = _snapshot(
    "SP100",
    "S&P 100 large-cap US equities (static snapshot 2026-05-28; not survivorship-free)",
    _SP100_SYMBOLS,
)

ETF_CORE = _snapshot(
    "ETFCORE",
    "Liquid long-history US-listed ETFs (static snapshot 2026-05-28; "
    "survivorship-robust by construction -- see module comment)",
    _ETF_CORE_SYMBOLS,
)

NASDAQ100 = _snapshot(
    "NDX",
    "NASDAQ 100 (static snapshot 2026-05-28; not survivorship-free)",
    _NDX_SYMBOLS,
)

NIFTY50 = _snapshot(
    "NIFTY50",
    "NSE NIFTY 50 Indian large caps (static snapshot 2026-05-28; not survivorship-free)",
    _NIFTY50_SYMBOLS,
)


BUILTIN_UNIVERSES: dict[str, Universe] = {
    "SP100": SP100,
    "NDX": NASDAQ100,
    "NIFTY50": NIFTY50,
    "ETFCORE": ETF_CORE,
}


def get_universe(name: str) -> Universe:
    """Look up a built-in universe by name."""
    key = name.upper()
    if key not in BUILTIN_UNIVERSES:
        raise KeyError(f"Unknown universe {name!r}. Known: {sorted(BUILTIN_UNIVERSES)}")
    return BUILTIN_UNIVERSES[key]


def utc_today() -> date:
    """UTC date for snapshot defaults."""
    return datetime.now(UTC).date()
