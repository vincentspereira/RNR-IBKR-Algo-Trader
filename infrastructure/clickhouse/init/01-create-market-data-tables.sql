-- ClickHouse market data tables
-- File: 01-create-market-data-tables.sql

-- OHLCV bars table
-- NOTE: this DDL must stay in sync with the canonical writer,
-- core_trading/data/storage.py (_BARS_DDL). ReplacingMergeTree keyed on
-- (symbol, resolution, timestamp) makes re-ingestion of overlapping windows
-- idempotent. No TTL: Phase 1 requires at least 5 years of daily history
-- (the previous 2-year TTL silently deleted required backtest data).
CREATE TABLE IF NOT EXISTS market_data.bars (
    symbol String,
    resolution String,
    timestamp DateTime64(3, 'UTC'),
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    adjusted_close Nullable(Float64),
    vwap Nullable(Float64),
    trade_count Nullable(Int64),
    source String,
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(ingested_at)
ORDER BY (symbol, resolution, timestamp);

-- Tick data table
CREATE TABLE IF NOT EXISTS market_data.ticks (
    symbol String,
    timestamp DateTime64(3),
    bid Float64,
    ask Float64,
    last_price Float64,
    bid_size Float64,
    ask_size Float64,
    last_size Float64,
    volume Float64 DEFAULT 0,
    source String DEFAULT 'ibkr'
) ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(timestamp)
ORDER BY (symbol, timestamp)
TTL timestamp + INTERVAL 90 DAY;

-- Index for symbol lookups
ALTER TABLE market_data.ticks ADD INDEX idx_ticks_symbol (symbol) TYPE minmax GRANULARITY 4;

-- Quotes cache table (latest snapshot per symbol)
CREATE TABLE IF NOT EXISTS market_data.quotes (
    symbol String,
    timestamp DateTime64(3),
    bid Float64,
    ask Float64,
    last_price Float64,
    bid_size Float64,
    ask_size Float64,
    volume Float64 DEFAULT 0,
    high Float64 DEFAULT 0,
    low Float64 DEFAULT 0,
    close Float64 DEFAULT 0,
    source String DEFAULT 'ibkr'
) ENGINE = ReplacingMergeTree(timestamp)
ORDER BY symbol
TTL timestamp + INTERVAL 7 DAY;
