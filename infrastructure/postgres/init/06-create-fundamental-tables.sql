-- Fundamental Analysis schema tables (NEW - Phase 15.5)
-- File: 06-create-fundamental-tables.sql

-- Companies table
CREATE TABLE fundamental.companies (
    company_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(10) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    exchange VARCHAR(50),
    sector VARCHAR(100),
    industry VARCHAR(100),
    market_cap DECIMAL(20, 2),
    employees INTEGER,
    description TEXT,
    website VARCHAR(255),
    ceo VARCHAR(100),
    headquarters VARCHAR(255),
    founded_year INTEGER,
    fiscal_year_end VARCHAR(10),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Financial statements table
CREATE TABLE fundamental.financial_statements (
    statement_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    period_end DATE NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_quarter INTEGER CHECK (fiscal_quarter BETWEEN 1 AND 4),
    statement_type VARCHAR(20) NOT NULL CHECK (statement_type IN ('INCOME', 'BALANCE', 'CASH_FLOW')),
    data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id) ON DELETE CASCADE,
    CONSTRAINT unique_statement UNIQUE (company_id, period_end, statement_type)
);

-- Financial ratios table (50+ ratios)
CREATE TABLE fundamental.financial_ratios (
    ratio_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    period_end DATE NOT NULL,
    
    -- Liquidity Ratios
    current_ratio DECIMAL(10, 4),
    quick_ratio DECIMAL(10, 4),
    cash_ratio DECIMAL(10, 4),
    operating_cash_flow_ratio DECIMAL(10, 4),
    
    -- Profitability Ratios
    gross_margin DECIMAL(10, 4),
    operating_margin DECIMAL(10, 4),
    net_margin DECIMAL(10, 4),
    roe DECIMAL(10, 4),
    roa DECIMAL(10, 4),
    roic DECIMAL(10, 4),
    roce DECIMAL(10, 4),
    
    -- Leverage Ratios
    debt_to_equity DECIMAL(10, 4),
    debt_to_assets DECIMAL(10, 4),
    equity_multiplier DECIMAL(10, 4),
    interest_coverage DECIMAL(10, 4),
    debt_service_coverage DECIMAL(10, 4),
    
    -- Efficiency Ratios
    asset_turnover DECIMAL(10, 4),
    inventory_turnover DECIMAL(10, 4),
    receivables_turnover DECIMAL(10, 4),
    payables_turnover DECIMAL(10, 4),
    fixed_asset_turnover DECIMAL(10, 4),
    
    -- Valuation Ratios
    pe_ratio DECIMAL(10, 4),
    pb_ratio DECIMAL(10, 4),
    ps_ratio DECIMAL(10, 4),
    peg_ratio DECIMAL(10, 4),
    ev_to_ebitda DECIMAL(10, 4),
    ev_to_sales DECIMAL(10, 4),
    price_to_fcf DECIMAL(10, 4),
    
    -- Growth Ratios
    revenue_growth_yoy DECIMAL(10, 4),
    earnings_growth_yoy DECIMAL(10, 4),
    eps_growth_yoy DECIMAL(10, 4),
    
    -- Dividend Ratios
    dividend_yield DECIMAL(10, 4),
    dividend_payout_ratio DECIMAL(10, 4),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id) ON DELETE CASCADE,
    CONSTRAINT unique_ratio UNIQUE (company_id, period_end)
);

-- Quality scores table
CREATE TABLE fundamental.quality_scores (
    score_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    period_end DATE NOT NULL,
    
    -- Piotroski F-Score (0-9)
    piotroski_f_score INTEGER CHECK (piotroski_f_score BETWEEN 0 AND 9),
    piotroski_profitability INTEGER CHECK (piotroski_profitability BETWEEN 0 AND 4),
    piotroski_leverage INTEGER CHECK (piotroski_leverage BETWEEN 0 AND 3),
    piotroski_operating INTEGER CHECK (piotroski_operating BETWEEN 0 AND 2),
    
    -- Altman Z-Score
    altman_z_score DECIMAL(10, 4),
    altman_zone VARCHAR(20) CHECK (altman_zone IN ('SAFE', 'GREY', 'DISTRESS')),
    
    -- Beneish M-Score
    beneish_m_score DECIMAL(10, 4),
    beneish_probability DECIMAL(5, 4),
    
    -- Composite Quality Score (0-100)
    composite_score DECIMAL(5, 2) CHECK (composite_score BETWEEN 0 AND 100),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id) ON DELETE CASCADE,
    CONSTRAINT unique_quality_score UNIQUE (company_id, period_end)
);

-- Valuation models table
CREATE TABLE fundamental.valuation_models (
    valuation_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- DCF Model
    dcf_intrinsic_value DECIMAL(18, 2),
    dcf_wacc DECIMAL(10, 4),
    dcf_terminal_growth DECIMAL(10, 4),
    dcf_fcf_projections JSONB,
    
    -- DDM Model
    ddm_intrinsic_value DECIMAL(18, 2),
    ddm_growth_rate DECIMAL(10, 4),
    ddm_required_return DECIMAL(10, 4),
    
    -- Graham Number
    graham_number DECIMAL(18, 2),
    
    -- PEG Valuation
    peg_fair_value DECIMAL(18, 2),
    
    -- EV Multiples
    ev_ebitda_fair_value DECIMAL(18, 2),
    
    -- Composite Fair Value
    composite_fair_value DECIMAL(18, 2),
    current_price DECIMAL(18, 2),
    upside_potential DECIMAL(10, 4),
    
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id) ON DELETE CASCADE
);

-- Earnings data table
CREATE TABLE fundamental.earnings_data (
    earnings_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    report_date DATE NOT NULL,
    fiscal_quarter INTEGER CHECK (fiscal_quarter BETWEEN 1 AND 4),
    fiscal_year INTEGER NOT NULL,
    eps_actual DECIMAL(10, 4),
    eps_estimate DECIMAL(10, 4),
    eps_surprise DECIMAL(10, 4),
    eps_surprise_percent DECIMAL(10, 4),
    revenue_actual DECIMAL(20, 2),
    revenue_estimate DECIMAL(20, 2),
    revenue_surprise DECIMAL(20, 2),
    revenue_surprise_percent DECIMAL(10, 4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id) ON DELETE CASCADE,
    CONSTRAINT unique_earnings UNIQUE (company_id, report_date)
);

-- Insider transactions table
CREATE TABLE fundamental.insider_transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    transaction_date DATE NOT NULL,
    insider_name VARCHAR(255),
    insider_title VARCHAR(255),
    transaction_type VARCHAR(20) CHECK (transaction_type IN ('BUY', 'SELL', 'OPTION_EXERCISE', 'GIFT')),
    shares DECIMAL(18, 8),
    price DECIMAL(18, 2),
    total_value DECIMAL(20, 2),
    shares_owned_after DECIMAL(18, 8),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id) ON DELETE CASCADE
);

-- ESG scores table
CREATE TABLE fundamental.esg_scores (
    esg_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL,
    score_date DATE NOT NULL,
    environmental_score DECIMAL(5, 2) CHECK (environmental_score BETWEEN 0 AND 100),
    social_score DECIMAL(5, 2) CHECK (social_score BETWEEN 0 AND 100),
    governance_score DECIMAL(5, 2) CHECK (governance_score BETWEEN 0 AND 100),
    total_esg_score DECIMAL(5, 2) CHECK (total_esg_score BETWEEN 0 AND 100),
    esg_rating VARCHAR(3) CHECK (esg_rating IN ('AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_company FOREIGN KEY (company_id) REFERENCES fundamental.companies(company_id) ON DELETE CASCADE,
    CONSTRAINT unique_esg_score UNIQUE (company_id, score_date)
);

-- Indexes
CREATE INDEX idx_companies_symbol ON fundamental.companies(symbol);
CREATE INDEX idx_companies_sector ON fundamental.companies(sector);
CREATE INDEX idx_companies_industry ON fundamental.companies(industry);

CREATE INDEX idx_financial_statements_company ON fundamental.financial_statements(company_id, period_end DESC);
CREATE INDEX idx_financial_statements_type ON fundamental.financial_statements(statement_type);

CREATE INDEX idx_financial_ratios_company ON fundamental.financial_ratios(company_id, period_end DESC);

CREATE INDEX idx_quality_scores_company ON fundamental.quality_scores(company_id, period_end DESC);
CREATE INDEX idx_quality_scores_piotroski ON fundamental.quality_scores(piotroski_f_score DESC);
CREATE INDEX idx_quality_scores_composite ON fundamental.quality_scores(composite_score DESC);

CREATE INDEX idx_valuation_models_company ON fundamental.valuation_models(company_id);
CREATE INDEX idx_earnings_data_company ON fundamental.earnings_data(company_id, report_date DESC);
CREATE INDEX idx_insider_transactions_company ON fundamental.insider_transactions(company_id, transaction_date DESC);
CREATE INDEX idx_esg_scores_company ON fundamental.esg_scores(company_id, score_date DESC);

-- Triggers
CREATE TRIGGER update_companies_updated_at BEFORE UPDATE ON fundamental.companies
    FOR EACH ROW EXECUTE FUNCTION users.update_updated_at_column();
