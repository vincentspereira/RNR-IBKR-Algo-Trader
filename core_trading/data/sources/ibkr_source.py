"""Interactive Brokers OHLCV adapter via ``ib_insync``.

This is the **primary** historical bar source for development and paper trading
per :doc:`docs/FREE_DATA_VENDORS.md` -- data is bundled with the broker account.

Design:

* ``ib_insync`` is imported lazily so that importing this module never fails
  when TWS / IB Gateway is absent. Construction also succeeds offline; the
  connection is established on first fetch (or explicitly via :meth:`connect`).
* The adapter manages its own connection, independent of the broker
  :class:`core_trading.adapters.ibkr_adapter.IBKRAdapter`, so data fetching and
  order placement have separate sessions (different clientId) and never
  contend.
* Connection parameters default to the ``IBKR_HOST`` / ``IBKR_PORT`` env vars,
  matching the broker adapter and ``.env`` conventions.

End-to-end validation against a live paper account is in ``tools/smoke_ibkr.py``.
Unit tests mock the ``IB`` client so they run offline.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import pandas as pd

from core_trading.data.bars import (
    Bar,
    BarRequest,
    BarResolution,
    BarSource,
    BarSourceCapabilities,
)


_RES_TO_IB_BARSIZE: dict[BarResolution, str] = {
    BarResolution.SECOND_1: "1 secs",
    BarResolution.SECOND_5: "5 secs",
    BarResolution.SECOND_30: "30 secs",
    BarResolution.MINUTE_1: "1 min",
    BarResolution.MINUTE_5: "5 mins",
    BarResolution.MINUTE_15: "15 mins",
    BarResolution.MINUTE_30: "30 mins",
    BarResolution.HOUR_1: "1 hour",
    BarResolution.DAY_1: "1 day",
    BarResolution.WEEK_1: "1 week",
    BarResolution.MONTH_1: "1 month",
}

_RES_TO_SECONDS: dict[BarResolution, int] = {
    BarResolution.SECOND_1: 1,
    BarResolution.SECOND_5: 5,
    BarResolution.SECOND_30: 30,
    BarResolution.MINUTE_1: 60,
    BarResolution.MINUTE_5: 300,
    BarResolution.MINUTE_15: 900,
    BarResolution.MINUTE_30: 1800,
    BarResolution.HOUR_1: 3600,
    BarResolution.DAY_1: 86_400,
    BarResolution.WEEK_1: 604_800,
    BarResolution.MONTH_1: 2_592_000,
}


def _ib_duration(start: datetime, end: datetime) -> str:
    """Translate a date window into an IB ``durationStr`` (e.g. '30 D', '2 Y')."""
    span_days = max(1, (end - start).days)
    if span_days <= 365:
        return f"{span_days} D"
    years = (span_days // 365) + 1
    return f"{years} Y"


class IBKRBarSource(BarSource):
    """OHLCV via Interactive Brokers historical data.

    Parameters
    ----------
    host, port:
        TWS / Gateway socket. Default from ``IBKR_HOST`` / ``IBKR_PORT`` env,
        falling back to ``127.0.0.1:7497`` (paper TWS).
    client_id:
        API client id. Use a distinct id from the broker adapter (default 7) so
        data and trading sessions do not collide.
    what_to_show:
        IB whatToShow field. ``TRADES`` for equities; ``MIDPOINT`` for FX.
    use_rth:
        Restrict to regular trading hours. Overridden per-request by
        ``BarRequest.include_extended_hours``.
    exchange, currency:
        Default contract routing for plain equity symbols.
    """

    _NAME = "ibkr"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int = 7,
        what_to_show: str = "TRADES",
        use_rth: bool = True,
        exchange: str = "SMART",
        currency: str = "USD",
    ) -> None:
        self._host = host if host is not None else os.environ.get("IBKR_HOST", "127.0.0.1")
        env_port = os.environ.get("IBKR_PORT", "7497")
        self._port = port if port is not None else int(env_port)
        self._client_id = client_id
        self._what_to_show = what_to_show
        self._use_rth = use_rth
        self._exchange = exchange
        self._currency = currency
        self._ib: Any = None

    @property
    def capabilities(self) -> BarSourceCapabilities:
        return BarSourceCapabilities(
            name=self._NAME,
            supports_resolutions=frozenset(_RES_TO_IB_BARSIZE.keys()),
            supports_extended_hours=True,
            supports_adjusted=False,
            supports_unadjusted=True,
            max_history_days=None,
            rate_limit_per_minute=None,
            requires_api_key=False,
        )

    def _load_ib(self) -> Any:
        try:
            from ib_insync import IB
        except ImportError as exc:  # pragma: no cover - exercised only without ib_insync
            raise RuntimeError(
                "ib_insync is required for IBKRBarSource. Install it or use "
                "YFinanceBarSource for development."
            ) from exc
        return IB

    async def connect(self) -> None:
        """Open the IB connection if not already connected."""
        if self._ib is not None and self._ib.isConnected():
            return
        ib_cls = self._load_ib()
        self._ib = ib_cls()
        await self._ib.connectAsync(
            host=self._host, port=self._port, clientId=self._client_id, timeout=15
        )

    async def disconnect(self) -> None:
        """Close the IB connection if open."""
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()

    def _make_contract(self, symbol: str) -> Any:
        from ib_insync import Stock

        return Stock(symbol, self._exchange, self._currency)

    def _native_barsize(self, resolution: BarResolution) -> str:
        if resolution not in _RES_TO_IB_BARSIZE:
            raise ValueError(
                f"IBKR does not support resolution {resolution!r}. "
                f"Supported: {sorted(r.value for r in _RES_TO_IB_BARSIZE)}"
            )
        return _RES_TO_IB_BARSIZE[resolution]

    @staticmethod
    def _bar_timestamp(raw_date: Any) -> datetime:
        """Coerce an ib_insync bar date/datetime into a tz-aware UTC datetime."""
        if isinstance(raw_date, datetime):
            dt = raw_date
        else:
            ts = pd.Timestamp(raw_date)
            dt = ts.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt

    async def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        barsize = self._native_barsize(request.resolution)
        await self.connect()
        from ib_insync import util as _ib_util  # noqa: F401  (ensures patchable import)

        all_bars: list[Bar] = []
        duration = _ib_duration(request.start, request.end)
        end_dt = request.end.astimezone(timezone.utc).strftime("%Y%m%d %H:%M:%S UTC")
        use_rth = not request.include_extended_hours and self._use_rth

        for symbol in request.symbols:
            contract = self._make_contract(symbol)
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                raise RuntimeError(f"could not qualify IBKR contract for {symbol!r}")
            ib_bars = await self._ib.reqHistoricalDataAsync(
                qualified[0],
                endDateTime=end_dt,
                durationStr=duration,
                barSizeSetting=barsize,
                whatToShow=self._what_to_show,
                useRTH=use_rth,
                formatDate=2,
            )
            for b in ib_bars:
                ts = self._bar_timestamp(b.date)
                if ts < request.start or ts > request.end:
                    continue
                all_bars.append(
                    Bar(
                        symbol=symbol,
                        timestamp=ts,
                        resolution=request.resolution,
                        open=float(b.open),
                        high=float(b.high),
                        low=float(b.low),
                        close=float(b.close),
                        volume=float(b.volume) if b.volume is not None and b.volume >= 0 else 0.0,
                        source=self._NAME,
                        adjusted_close=None,
                        vwap=float(b.average) if getattr(b, "average", None) is not None else None,
                        trade_count=int(b.barCount) if getattr(b, "barCount", None) else None,
                    )
                )

        df = BarSource.bars_to_dataframe(all_bars)
        if not df.empty:
            BarSource.validate_dataframe(df)
        return df

    async def stream_bars(self, request: BarRequest) -> AsyncIterator[Bar]:
        df = await self.fetch_bars(request)
        for (symbol, timestamp), row in df.iterrows():
            yield Bar(
                symbol=str(symbol),
                timestamp=timestamp.to_pydatetime() if isinstance(timestamp, pd.Timestamp) else timestamp,
                resolution=request.resolution,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]) if not pd.isna(row["volume"]) else 0.0,
                source=self._NAME,
                adjusted_close=None,
                vwap=float(row["vwap"]) if not pd.isna(row["vwap"]) else None,
                trade_count=int(row["trade_count"]) if not pd.isna(row["trade_count"]) else None,
            )

    def expected_seconds(self, resolution: BarResolution) -> int | None:
        return _RES_TO_SECONDS.get(resolution)
