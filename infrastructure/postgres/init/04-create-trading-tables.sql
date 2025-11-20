-- Trading schema tables
-- File: 04-create-trading-tables.sql

-- Orders table
CREATE TABLE trading.orders (
    order_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    strategy_id UUID,
    symbol VARCHAR(10) NOT NULL,
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT', 'TRAILING_STOP')),
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(18, 8) NOT NULL CHECK (quantity > 0),
    price DECIMAL(18, 8),
    limit_price DECIMAL(18, 8),
    stop_price DECIMAL(18, 8),
    trail_amount DECIMAL(18, 8),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SUBMITTED', 'FILLED', 'PARTIALLY_FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED')),
    broker_order_id VARCHAR(100),
    filled_quantity DECIMAL(18, 8) DEFAULT 0,
    avg_fill_price DECIMAL(18, 8),
    commission DECIMAL(18, 8) DEFAULT 0,
    time_in_force VARCHAR(10) DEFAULT 'DAY' CHECK (time_in_force IN ('DAY', 'GTC', 'IOC', 'FOK')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP WITH TIME ZONE,
    filled_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users.users(user_id),
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id)
);

-- Trades table (executions)
CREATE TABLE trading.trades (
    trade_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(18, 8) NOT NULL,
    price DECIMAL(18, 8) NOT NULL,
    commission DECIMAL(18, 8) DEFAULT 0,
    broker_trade_id VARCHAR(100),
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_order FOREIGN KEY (order_id) REFERENCES trading.orders(order_id)
);

-- Positions table
CREATE TABLE trading.positions (
    position_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    strategy_id UUID,
    symbol VARCHAR(10) NOT NULL,
    quantity DECIMAL(18, 8) NOT NULL,
    avg_entry_price DECIMAL(18, 8) NOT NULL,
    current_price DECIMAL(18, 8),
    unrealized_pnl DECIMAL(18, 8),
    realized_pnl DECIMAL(18, 8) DEFAULT 0,
    total_commission DECIMAL(18, 8) DEFAULT 0,
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP WITH TIME ZONE,
    is_open BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users.users(user_id),
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id),
    CONSTRAINT unique_open_position UNIQUE (user_id, symbol, is_open) WHERE is_open = TRUE
);

-- Trading signals table
CREATE TABLE trading.signals (
    signal_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    signal_type VARCHAR(10) NOT NULL CHECK (signal_type IN ('BUY', 'SELL', 'HOLD')),
    strength DECIMAL(5, 4) CHECK (strength BETWEEN 0 AND 1),
    price DECIMAL(18, 8),
    quantity DECIMAL(18, 8),
    reasoning TEXT,
    indicators JSONB DEFAULT '{}'::jsonb,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    executed BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id)
);

-- Indexes
CREATE INDEX idx_orders_user_id ON trading.orders(user_id);
CREATE INDEX idx_orders_strategy_id ON trading.orders(strategy_id);
CREATE INDEX idx_orders_symbol ON trading.orders(symbol);
CREATE INDEX idx_orders_status ON trading.orders(status);
CREATE INDEX idx_orders_created_at ON trading.orders(created_at DESC);

CREATE INDEX idx_trades_order_id ON trading.trades(order_id);
CREATE INDEX idx_trades_symbol ON trading.trades(symbol);
CREATE INDEX idx_trades_executed_at ON trading.trades(executed_at DESC);

CREATE INDEX idx_positions_user_id ON trading.positions(user_id);
CREATE INDEX idx_positions_strategy_id ON trading.positions(strategy_id);
CREATE INDEX idx_positions_symbol ON trading.positions(symbol);
CREATE INDEX idx_positions_is_open ON trading.positions(is_open);

CREATE INDEX idx_signals_strategy_id ON trading.signals(strategy_id);
CREATE INDEX idx_signals_symbol ON trading.signals(symbol);
CREATE INDEX idx_signals_generated_at ON trading.signals(generated_at DESC);
CREATE INDEX idx_signals_executed ON trading.signals(executed);

-- Trigger for updated_at
CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON trading.orders
    FOR EACH ROW EXECUTE FUNCTION users.update_updated_at_column();

CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON trading.positions
    FOR EACH ROW EXECUTE FUNCTION users.update_updated_at_column();
