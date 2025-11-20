-- Create database schemas
-- File: 02-create-schemas.sql

-- Trading schema: Orders, trades, positions, signals
CREATE SCHEMA IF NOT EXISTS trading;

-- Portfolio schema: Accounts, holdings, performance
CREATE SCHEMA IF NOT EXISTS portfolio;

-- Users schema: Authentication, roles, permissions
CREATE SCHEMA IF NOT EXISTS users;

-- Fundamental schema: Financial statements, ratios, scores (NEW - Phase 15.5)
CREATE SCHEMA IF NOT EXISTS fundamental;

-- Strategy schema: Strategies, backtests, versions
CREATE SCHEMA IF NOT EXISTS strategy;

-- System schema: Configuration, audit logs
CREATE SCHEMA IF NOT EXISTS system;

-- Grant all privileges to trading_user
GRANT ALL ON SCHEMA trading TO trading_user;
GRANT ALL ON SCHEMA portfolio TO trading_user;
GRANT ALL ON SCHEMA users TO trading_user;
GRANT ALL ON SCHEMA fundamental TO trading_user;
GRANT ALL ON SCHEMA strategy TO trading_user;
GRANT ALL ON SCHEMA system TO trading_user;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA trading GRANT ALL ON TABLES TO trading_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA portfolio GRANT ALL ON TABLES TO trading_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA users GRANT ALL ON TABLES TO trading_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamental GRANT ALL ON TABLES TO trading_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA strategy GRANT ALL ON TABLES TO trading_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA system GRANT ALL ON TABLES TO trading_user;

-- Verify schemas created
SELECT 
    nspname AS schema_name,
    nspowner::regrole AS owner
FROM pg_namespace
WHERE nspname IN ('trading', 'portfolio', 'users', 'fundamental', 'strategy', 'system')
ORDER BY nspname;
