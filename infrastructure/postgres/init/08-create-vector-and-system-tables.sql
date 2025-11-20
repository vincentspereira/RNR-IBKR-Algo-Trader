-- Vector embeddings and system tables
-- File: 08-create-vector-and-system-tables.sql

-- Strategy embeddings table (for similarity search)
CREATE TABLE strategy.strategy_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID NOT NULL,
    embedding vector(384),  -- Using all-MiniLM-L6-v2 or snowflake-arctic-embed2:568m (1024d)
    model_name VARCHAR(100) DEFAULT 'all-MiniLM-L6-v2',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_strategy FOREIGN KEY (strategy_id) REFERENCES strategy.strategies(strategy_id) ON DELETE CASCADE,
    CONSTRAINT unique_strategy_embedding UNIQUE (strategy_id)
);

-- Create vector similarity index (HNSW - Hierarchical Navigable Small World)
CREATE INDEX idx_strategy_embeddings_vector 
ON strategy.strategy_embeddings 
USING hnsw (embedding vector_cosine_ops);

-- Conversation embeddings table (for AI context)
CREATE TABLE system.conversation_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    embedding vector(384),
    model_name VARCHAR(100) DEFAULT 'all-MiniLM-L6-v2',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users.users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_conversation_embeddings_vector 
ON system.conversation_embeddings 
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_conversation_embeddings_user ON system.conversation_embeddings(user_id);
CREATE INDEX idx_conversation_embeddings_conversation ON system.conversation_embeddings(conversation_id);

-- System configuration table
CREATE TABLE system.configuration (
    config_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key VARCHAR(255) UNIQUE NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    is_encrypted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by UUID,
    CONSTRAINT fk_updated_by FOREIGN KEY (updated_by) REFERENCES users.users(user_id)
);

-- Audit log table
CREATE TABLE system.audit_log (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100),
    entity_id UUID,
    old_values JSONB,
    new_values JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users.users(user_id)
);

-- System events table
CREATE TABLE system.events (
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type VARCHAR(100) NOT NULL,
    severity VARCHAR(20) CHECK (severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    service_name VARCHAR(100),
    message TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_configuration_key ON system.configuration(key);
CREATE INDEX idx_audit_log_user_id ON system.audit_log(user_id);
CREATE INDEX idx_audit_log_entity ON system.audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_log_created_at ON system.audit_log(created_at DESC);
CREATE INDEX idx_events_type ON system.events(event_type);
CREATE INDEX idx_events_severity ON system.events(severity);
CREATE INDEX idx_events_created_at ON system.events(created_at DESC);

-- Triggers
CREATE TRIGGER update_configuration_updated_at BEFORE UPDATE ON system.configuration
    FOR EACH ROW EXECUTE FUNCTION users.update_updated_at_column();

-- Insert default system configuration
INSERT INTO system.configuration (key, value, description) VALUES
('system.version', '"1.0.0"'::jsonb, 'System version'),
('features.live_trading', 'false'::jsonb, 'Enable live trading'),
('features.options_trading', 'true'::jsonb, 'Enable options trading'),
('features.ml_strategies', 'true'::jsonb, 'Enable ML/DL strategies'),
('features.fundamental_analysis', 'true'::jsonb, 'Enable fundamental analysis'),
('limits.max_strategies_per_user', '50'::jsonb, 'Maximum strategies per user'),
('limits.max_positions_per_strategy', '20'::jsonb, 'Maximum positions per strategy'),
('limits.max_daily_trades', '1000'::jsonb, 'Maximum daily trades per user');

-- Create view for active deployments
CREATE VIEW strategy.active_deployments AS
SELECT 
    ds.deployment_id,
    ds.strategy_id,
    s.name AS strategy_name,
    s.user_id,
    u.username,
    ds.mode,
    ds.capital_allocated,
    ds.symbols,
    ds.deployed_at,
    ds.performance_metrics
FROM strategy.deployed_strategies ds
JOIN strategy.strategies s ON ds.strategy_id = s.strategy_id
JOIN users.users u ON s.user_id = u.user_id
WHERE ds.is_active = TRUE;

-- Create view for portfolio summary
CREATE VIEW portfolio.portfolio_summary AS
SELECT 
    p.portfolio_id,
    p.user_id,
    u.username,
    p.name,
    p.initial_capital,
    p.current_value,
    p.cash_balance,
    p.total_pnl,
    p.total_pnl_percent,
    COUNT(h.holding_id) AS total_holdings,
    SUM(h.market_value) AS total_holdings_value
FROM portfolio.portfolios p
JOIN users.users u ON p.user_id = u.user_id
LEFT JOIN portfolio.holdings h ON p.portfolio_id = h.portfolio_id
WHERE p.is_active = TRUE
GROUP BY p.portfolio_id, p.user_id, u.username, p.name, p.initial_capital, 
         p.current_value, p.cash_balance, p.total_pnl, p.total_pnl_percent;

-- Grant permissions on views
GRANT SELECT ON strategy.active_deployments TO trading_user;
GRANT SELECT ON portfolio.portfolio_summary TO trading_user;
