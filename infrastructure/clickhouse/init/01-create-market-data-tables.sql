-- ClickHouse market data tables
-- File: 01-create-market-data-tables.sql

-- OHLCV bars table
CREATE TABLE IF NOT EXISTS market_data.bars (
    symbol String,
    timestamp DateTime64(3),
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    timeframe String,
    bar_count Int32 DEFAULT 0,
    average Float64 DEFAULT 0.0,
    source String DEFAULT 'ibkr'
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (symbol, timeframe, timestamp)
TTL timestamp + INTERVAL 2 YEAR;

-- Indexes for common queries
ALTER TABLE market_data.bars ADD INDEX idx_bars_symbol_timeframe (symbol, timeframe) TYPE minmax GRANULARITY 4;

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
