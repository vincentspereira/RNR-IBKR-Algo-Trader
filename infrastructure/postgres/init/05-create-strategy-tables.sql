-- Strategy schema tables
-- File: 05-create-strategy-tables.sql

-- Strategies table
CREATE TABLE strategy.strategies (
    strategy_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    strategy_type VARCHAR(50) NOT NULL CHECK (strategy_type IN ('TECHNICAL', 'FUNDAMENTAL', 'ML', 'DL', 'RL', 'HYBRID', 'OPTIONS')),
    code TEXT NOT NULL,
    language VARCHAR(20) DEFAULT 'PYTHON' CHECK (language IN ('PYTHON', 'RUST')),
    parameters JSONB DEFAULT '{}'::jsonb,
    version VARCHAR(20) DEFAULT '1.0.0',
    is_active BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deployed_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users.users(user_id),
    CONSTRAINT unique_user_strategy_name UNIQUE (user_id, name)
);

-- Strategy versions table
CREATE TABLE strategy.strategy_versions (
    version_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL,
    version VARCHAR(20) NOT NULL,
    code TEXT NOT NULL,
    parameters JSONB DEFAULT '{}'::jsonb,
    changelog TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by UUID NOT NULL,
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id) ON DELETE CASCADE,
    CONSTRAINT fk_user FOREIGN KEY (created_by) REFERENCES users.users(user_id),
    CONSTRAINT unique_strategy_version UNIQUE (strategy_id, version)
);

-- Backtest results table
CREATE TABLE strategy.backtest_results (
    backtest_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL,
    version_id UUID,
    symbols TEXT[] NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital DECIMAL(18, 2) NOT NULL,
    final_capital DECIMAL(18, 2) NOT NULL,
    total_return DECIMAL(10, 4),
    annualized_return DECIMAL(10, 4),
    sharpe_ratio DECIMAL(10, 4),
    sortino_ratio DECIMAL(10, 4),
    max_drawdown DECIMAL(10, 4),
    win_rate DECIMAL(5, 4),
    profit_factor DECIMAL(10, 4),
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    avg_win DECIMAL(18, 2),
    avg_loss DECIMAL(18, 2),
    largest_win DECIMAL(18, 2),
    largest_loss DECIMAL(18, 2),
    execution_time_seconds INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    results_data JSONB,
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id) ON DELETE CASCADE,
    CONSTRAINT fk_version FOREIGN KEY (version_id) REFERENCES strategy.strategy_versions(version_id)
);

-- Deployed strategies table
CREATE TABLE strategy.deployed_strategies (
    deployment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL,
    version_id UUID,
    mode VARCHAR(10) NOT NULL CHECK (mode IN ('PAPER', 'LIVE')),
    capital_allocated DECIMAL(18, 2) NOT NULL,
    symbols TEXT[] NOT NULL,
    risk_limits JSONB DEFAULT '{}'::jsonb,
    deployed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    performance_metrics JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id),
    CONSTRAINT fk_version FOREIGN KEY (version_id) REFERENCES strategy.strategy_versions(version_id)
);

-- Indexes
CREATE INDEX idx_strategies_user_id ON strategy.strategies(user_id);
CREATE INDEX idx_strategies_type ON strategy.strategies(strategy_type);
CREATE INDEX idx_strategies_active ON strategy.strategies(is_active);
CREATE INDEX idx_strategies_public ON strategy.strategies(is_public);

CREATE INDEX idx_strategy_versions_strategy_id ON strategy.strategy_versions(strategy_id);
CREATE INDEX idx_backtest_results_strategy_id ON strategy.backtest_results(strategy_id);
CREATE INDEX idx_backtest_results_created_at ON strategy.backtest_results(created_at DESC);

CREATE INDEX idx_deployed_strategies_strategy_id ON strategy.deployed_strategies(strategy_id);
CREATE INDEX idx_deployed_strategies_active ON strategy.deployed_strategies(is_active);
CREATE INDEX idx_deployed_strategies_mode ON strategy.deployed_strategies(mode);

-- Triggers
CREATE TRIGGER update_strategies_updated_at BEFORE UPDATE ON strategy.strategies
    FOR EACH ROW EXECUTE FUNCTION users.update_updated_at_column();
