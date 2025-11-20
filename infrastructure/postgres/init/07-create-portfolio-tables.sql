-- Portfolio schema tables
-- File: 07-create-portfolio-tables.sql

-- Portfolios table
CREATE TABLE portfolio.portfolios (
    portfolio_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    initial_capital DECIMAL(18, 2) NOT NULL,
    current_value DECIMAL(18, 2),
    cash_balance DECIMAL(18, 2),
    total_pnl DECIMAL(18, 2) DEFAULT 0,
    total_pnl_percent DECIMAL(10, 4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users.users(user_id),
    CONSTRAINT unique_user_portfolio_name UNIQUE (user_id, name)
);

-- Holdings table
CREATE TABLE portfolio.holdings (
    holding_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id UUID NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    quantity DECIMAL(18, 8) NOT NULL,
    avg_cost DECIMAL(18, 2) NOT NULL,
    current_price DECIMAL(18, 2),
    market_value DECIMAL(18, 2),
    unrealized_pnl DECIMAL(18, 2),
    unrealized_pnl_percent DECIMAL(10, 4),
    first_purchased_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio FOREIGN KEY (portfolio_id) REFERENCES portfolio.portfolios(portfolio_id) ON DELETE CASCADE,
    CONSTRAINT unique_portfolio_symbol UNIQUE (portfolio_id, symbol)
);

-- Performance metrics table
CREATE TABLE portfolio.performance_metrics (
    metric_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id UUID NOT NULL,
    date DATE NOT NULL,
    portfolio_value DECIMAL(18, 2) NOT NULL,
    cash_balance DECIMAL(18, 2) NOT NULL,
    total_pnl DECIMAL(18, 2),
    daily_return DECIMAL(10, 6),
    cumulative_return DECIMAL(10, 6),
    sharpe_ratio DECIMAL(10, 4),
    sortino_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 4),
    volatility DECIMAL(10, 4),
    beta DECIMAL(10, 4),
    alpha DECIMAL(10, 4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio FOREIGN KEY (portfolio_id) REFERENCES portfolio.portfolios(portfolio_id) ON DELETE CASCADE,
    CONSTRAINT unique_portfolio_date UNIQUE (portfolio_id, date)
);

-- Transactions table
CREATE TABLE portfolio.transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id UUID NOT NULL,
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'INTEREST', 'FEE')),
    amount DECIMAL(18, 2) NOT NULL,
    description TEXT,
    transaction_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_portfolio FOREIGN KEY (portfolio_id) REFERENCES portfolio.portfolios(portfolio_id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX idx_portfolios_user_id ON portfolio.portfolios(user_id);
CREATE INDEX idx_portfolios_active ON portfolio.portfolios(is_active);

CREATE INDEX idx_holdings_portfolio_id ON portfolio.holdings(portfolio_id);
CREATE INDEX idx_holdings_symbol ON portfolio.holdings(symbol);

CREATE INDEX idx_performance_metrics_portfolio_id ON portfolio.performance_metrics(portfolio_id, date DESC);

CREATE INDEX idx_transactions_portfolio_id ON portfolio.transactions(portfolio_id, transaction_date DESC);

-- Triggers
CREATE TRIGGER update_portfolios_updated_at BEFORE UPDATE ON portfolio.portfolios
    FOR EACH ROW EXECUTE FUNCTION users.update_updated_at_column();

CREATE TRIGGER update_holdings_updated_at BEFORE UPDATE ON portfolio.holdings
    FOR EACH ROW EXECUTE FUNCTION users.update_updated_at_column();
