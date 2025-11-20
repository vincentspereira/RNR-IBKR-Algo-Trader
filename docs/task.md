# Task Breakdown: Agentic AI Algorithmic Trading System

## Version 5.0 - Professional Edition with Fundamental Analysis

**Last Updated**: 2025-01-20  
**Total Phases**: 28  
**Timeline**: 55 weeks (42 weeks development + 90 days paper trading)  
**Test Coverage**: >95% required

---

## Overview

Build a professional-grade, institutional-quality Agentic AI-based Algorithmic Trading System with 20+ core services, **comprehensive fundamental analysis**, advanced options trading, ML/DL/RL strategies, TradingView-like charting, and continuous testing. Complete system runs locally on laptop for $10-100/month.

**Version 5.0 Major Addition**: Phase 15.5 - Fundamental Analysis System (rebuilt from scratch with enhanced features)

---

## Phase 1: Planning & Architecture Review (Weeks 1-2)

### Repository Review

- [/] Review entire repository structure
- [/] Analyze existing `core_trading` directory (109 Python files)
  - [x] Multi-Time Frame Engine
  - [x] Smart Money Engine
  - [x] Technical Indicators (50+)
  - [x] Candlestick Patterns
  - [x] Market Structures (Gann, Fibonacci, Elliott)
  - [x] Trading Strategies

### Architecture Planning

- [ ] Define all 28 microservices boundaries
- [ ] Design database schemas (all 5 databases)
  - [ ] PostgreSQL: Transactional data + fundamentals
  - [ ] ClickHouse: Time-series + audit logs
  - [ ] Neo4j: Knowledge graph
  - [ ] Redis: Caching
  - [ ] Qdrant: Vector embeddings
- [ ] Design Kafka topic hierarchy
  - [ ] marketdata.\* topics
  - [ ] trading.\* topics
  - [ ] risk.\* topics
  - [ ] fundamental.\* topics (NEW)
  - [ ] ai.\* topics
- [ ] Create sequence diagrams for critical workflows
- [ ] Define API contracts (OpenAPI 3.0 specs)

### Documentation

- [ ] Create Architecture Decision Records (ADRs)
- [ ] Create deployment architecture diagrams
- [ ] Document technology stack decisions
- [ ] Create integration strategy document

### User Approval

- [ ] Present complete plan to user
- [ ] Incorporate feedback
- [ ] Get final approval

**Testing**: Architecture validation, documentation review  
**Success Criteria**: Complete plan approved by user

---

## Phase 2: Documentation Updates (Weeks 2-3)

### Core Documentation

- [ ] Update README.md with v5.0 overview
  - [ ] System architecture diagram
  - [ ] Feature list (with fundamentals)
  - [ ] Setup instructions
  - [ ] Quick start guide
- [ ] Update all specs/ files
- [ ] Update all docs/ files

### API Documentation

- [ ] Create OpenAPI 3.0 specs for all services
- [ ] Document REST endpoints
- [ ] Document WebSocket API
- [ ] Create API usage examples
- [ ] Document authentication flows

### Deployment Documentation

- [ ] Local deployment guide (Docker Compose)
- [ ] Laptop-only deployment guide
- [ ] Hybrid deployment guide (Laptop + VPS)
- [ ] Cloud deployment guide (optional)

### Educational Content (NEW)

- [ ] Create interactive tutorials
  - [ ] Setup walkthrough
  - [ ] Paper trading tutorial
  - [ ] Strategy creation tutorial
  - [ ] Fundamental analysis tutorial (NEW)
- [ ] Record video walkthroughs
  - [ ] 15-min quick start
  - [ ] 30-min deep dive
  - [ ] Trading workflow demo
- [ ] Create strategy templates library
  - [ ] Day trading template
  - [ ] Swing trading template
  - [ ] Options template
  - [ ] Multi-factor template (technical + fundamental) (NEW)
  - [ ] ML/DL strategy template
- [ ] Document best practices
- [ ] Document common pitfalls
- [ ] Create comprehensive FAQ

**Testing**: Documentation review, link validation  
**Success Criteria**: All documentation complete and reviewed

---

## Phase 3: Infrastructure & Database Setup (Weeks 3-5)

### Docker Compose Configuration

- [ ] Create docker-compose.yml (development)
- [ ] Create docker-compose.prod.yml (production)
- [ ] Configure trading_network
- [ ] Set up volume mounts
- [ ] Configure .env files
- [ ] Set up health checks
- [ ] Configure restart policies

### PostgreSQL 17 + pgvector (DB 1)

- [ ] Deploy container
- [ ] Enable pgvector extension
- [ ] Create database schemas
  - [ ] Trading schema
  - [ ] Portfolio schema
  - [ ] User schema
  - [ ] Fundamental schema (NEW)
- [ ] Set up connection pooling (PgBouncer)
- [ ] Configure automatic backups
- [ ] Set up replication (optional)

### ClickHouse 24.8 (DB 2)

- [ ] Deploy container
- [ ] Create time-series tables
  - [ ] market_data_tick
  - [ ] market_data_1min
  - [ ] market_data_daily
  - [ ] audit_log
- [ ] Set up partitioning (by date + symbol)
- [ ] Configure retention policies
  - [ ] Tick data: 90 days
  - [ ] 1-min bars: 2 years
  - [ ] Daily bars: 10 years
- [ ] Enable compression (10-20x)

### Neo4j 5.25.0 (DB 3)

- [ ] Deploy container
- [ ] Configure memory (heap 2G, pagecache 1G)
- [ ] Create knowledge graph schema
  - [ ] Strategy nodes
  - [ ] Agent nodes
  - [ ] Workflow relationships
- [ ] Set up indexes and constraints

### Redis 7.4 (DB 4)

- [ ] Deploy container
- [ ] Configure persistence (AOF)
- [ ] Set eviction policy (LRU)
- [ ] Configure memory limit
- [ ] Set up clustering (if needed)

### Qdrant 1.12.0 (DB 5)

- [ ] Deploy container
- [ ] Create vector collections
  - [ ] strategy_embeddings
  - [ ] document_embeddings
- [ ] Configure HNSW parameters
- [ ] Set up distance metrics

### Apache Kafka 3.9

- [ ] Deploy Kafka (KRaft mode, no ZooKeeper)
- [ ] Deploy Schema Registry 7.7
- [ ] Create topic hierarchy
- [ ] Configure retention (hours + bytes)
- [ ] Set up replication factor
- [ ] Configure partitioning strategy

### GPU Acceleration

- [ ] Install NVIDIA Container Toolkit
- [ ] Configure Docker GPU access
- [ ] Install PyTorch 2.6.0+cu126
- [ ] Install CUDA 12.6
- [ ] Test GPU in containers
- [ ] Run GPU benchmark

### Cognee Memory Server

- [ ] Link to: C:\Users\Vincent_Pereira\Projects\AI Agents\enhanced-cognee
- [ ] Configure as MCP server
- [ ] Test memory persistence
- [ ] Verify integration

### Keycloak 26.0

- [ ] Deploy container
- [ ] Configure realm: "trading"
- [ ] Create users and roles
- [ ] Configure OIDC clients
- [ ] Test authentication flow

### Backup System (NEW)

- [ ] Create automated backup scripts
- [ ] Configure backup schedule
  - [ ] Databases: Hourly
  - [ ] Configurations: Daily
  - [ ] Strategies: On change
- [ ] Set up external drive backup
- [ ] Create backup verification scripts
- [ ] Test restore procedures
- [ ] Document recovery runbook

**Testing**:

- Database connectivity tests
- Kafka message flow tests
- Docker health checks
- GPU acceleration tests
- Backup/restore tests

**Success Criteria**: All infrastructure healthy and tested

---

## Phase 4: Microservices Architecture Foundation (Weeks 5-7)

### Directory Structure

- [ ] Create complete services/ structure
  - [ ] services/trading-engine/
  - [ ] services/market-data/
  - [ ] services/risk-manager/
  - [ ] services/portfolio-manager/
  - [ ] services/order-management/
  - [ ] services/fundamental-analysis/ (NEW)
  - [ ] services/market-scanner/
  - [ ] services/options-service/
  - [ ] services/ai-assistant/
  - [ ] services/guidance-service/
  - [ ] services/charting-service/
  - [ ] services/journal-service/
  - [ ] services/compliance-service/
  - [ ] services/api-gateway/

### Shared Libraries

- [ ] libs/common/events/
  - [ ] Base event classes
  - [ ] All event types
- [ ] libs/common/auth/
  - [ ] JWT handler
  - [ ] OAuth2 client
  - [ ] RBAC helpers
- [ ] libs/common/monitoring/
  - [ ] Prometheus metrics
  - [ ] Logging config
  - [ ] Tracing utilities
- [ ] libs/common/config/
  - [ ] Environment config
  - [ ] Feature flags
  - [ ] Settings validation
- [ ] libs/trading/indicators/
  - [ ] TA-Lib wrappers
  - [ ] Custom indicators
- [ ] libs/trading/models/
  - [ ] Order models
  - [ ] Position models
  - [ ] Market data models
- [ ] libs/fundamental/calculators/ (NEW)
  - [ ] Ratio calculator
  - [ ] Valuation calculator
  - [ ] Quality calculator
- [ ] libs/ai/models/
  - [ ] PyTorch models
  - [ ] Inference helpers

### CI/CD Pipeline

- [ ] .github/workflows/test.yml
- [ ] .github/workflows/build.yml
- [ ] .github/workflows/deploy.yml
- [ ] Configure pre-commit hooks
  - [ ] Black formatting
  - [ ] isort
  - [ ] Bandit security
  - [ ] mypy type checking
- [ ] Set up code coverage reporting

### Kafka Topics

- [ ] Define all topics
- [ ] Configure Schema Registry schemas
- [ ] Set up DLQ (dead letter queue)
- [ ] Test wildcard subscriptions

**Testing**:

- Service startup tests
- Inter-service communication
- Event schema validation
- CI/CD pipeline tests

**Success Criteria**: Microservices skeleton operational, CI/CD working

---

## Phase 5: Data Pipeline & Event Architecture (Weeks 7-9)

[Continue with detailed tasks for phases 5-14.5 following same pattern...]

---

## Phase 15.5: Fundamental Analysis System (Weeks 25-28) - **DETAILED NEW IN V5.0**

**Objective**: Build institutional-grade fundamental analysis with all features from existing FA platform PLUS enhanced capabilities

### Week 1: Core Infrastructure & Database Models (Week 25)

#### Service Setup

- [ ] Create `services/fundamental-analysis/` directory
- [ ] Initialize FastAPI application
  - [ ] app/main.py with CORS, middleware
  - [ ] app/**init**.py
  - [ ] app/core/config.py (settings)
  - [ ] app/core/security.py (auth)
- [ ] Set up async database connections
  - [ ] PostgreSQL async engine
  - [ ] Connection pooling
  - [ ] Session management
- [ ] Configure Kafka producers
  - [ ] fundamental.score.{symbol}
  - [ ] fundamental.alert.{symbol}
  - [ ] fundamental.data_quality.{symbol}
- [ ] Configure Kafka consumers
  - [ ] Subscribe to symbol.added
  - [ ] Subscribe to price.updated
- [ ] Set up Redis caching
  - [ ] Cache client configuration
  - [ ] TTL policies
  - [ ] Cache warming logic

#### Database Models (PostgreSQL)

- [ ] **Company Model** (`app/models/company.py`):

  ```python
  class Company:
      - id: UUID (PK)
      - symbol: String(10) (unique, indexed)
      - name: String(255)
      - sector: String(100)
      - industry: String(100)
      - exchange: String(10)
      - country: String(2)
      - market_cap: Numeric
      - shares_outstanding: BigInteger
      - founded_date: Date
      - headquarters: String(255)
      - employees: Integer
      - description: Text
      - website: String(255)
      - created_at: DateTime
      - updated_at: DateTime
  ```

  - [ ] Create model class
  - [ ] Add indexes (symbol, sector, industry)
  - [ ] Add relationships
  - [ ] Add validation

- [ ] **FinancialStatement Model** (`app/models/financial_statement.py`):

  ```python
  class FinancialStatement:
      - id: UUID (PK)
      - company_id: UUID (FK → Company)
      - period_type: Enum('quarterly', 'annual')
      - fiscal_year: Integer
      - fiscal_quarter: Integer (nullable)
      - statement_type: Enum('income', 'balance', 'cashflow')
      - filing_date: Date
      - period_end_date: Date

      # Income Statement Fields
      - revenue: Numeric
      - cost_of_revenue: Numeric
      - gross_profit: Numeric
      - operating_expenses: Numeric
      - operating_income: Numeric
      - interest_expense: Numeric
      - tax_expense: Numeric
      - net_income: Numeric
      - eps_basic: Numeric
      - eps_diluted: Numeric
      - ebitda: Numeric
      - ebit: Numeric

      # Balance Sheet Fields
      - total_assets: Numeric
      - current_assets: Numeric
      - cash: Numeric
      - accounts_receivable: Numeric
      - inventory: Numeric
      - total_liabilities: Numeric
      - current_liabilities: Numeric
      - long_term_debt: Numeric
      - shareholders_equity: Numeric
      - retained_earnings: Numeric
      - working_capital: Numeric

      # Cash Flow Fields
      - operating_cash_flow: Numeric
      - investing_cash_flow: Numeric
      - financing_cash_flow: Numeric
      - free_cash_flow: Numeric
      - capital_expenditures: Numeric

      - created_at: DateTime
      - updated_at: DateTime
  ```

  - [ ] Create model with all fields
  - [ ] Add composite indexes
  - [ ] Add validation rules
  - [ ] Add calculated properties

- [ ] **FinancialRatio Model** (`app/models/financial_ratio.py`):

  ```python
  class FinancialRatio:
      - id: UUID (PK)
      - company_id: UUID (FK)
      - period_type: Enum
      - fiscal_year: Integer
      - fiscal_quarter: Integer
      - calculation_date: Date

      # Liquidity Ratios (10)
      - current_ratio: Numeric
      - quick_ratio: Numeric
      - cash_ratio: Numeric
      - operating_cash_flow_ratio: Numeric
      - working_capital_ratio: Numeric
      - days_sales_outstanding: Numeric
      - days_inventory_outstanding: Numeric
      - days_payable_outstanding: Numeric
      - cash_conversion_cycle: Numeric
      - defensive_interval_ratio: Numeric

      # Profitability Ratios (12)
      - gross_profit_margin: Numeric
      - operating_profit_margin: Numeric
      - net_profit_margin: Numeric
      - ebitda_margin: Numeric
      - ebit_margin: Numeric
      - return_on_assets: Numeric
      - return_on_equity: Numeric
      - return_on_invested_capital: Numeric
      - return_on_capital_employed: Numeric
      - asset_turnover: Numeric
      - equity_multiplier: Numeric
      - tax_burden_ratio: Numeric

      # Leverage Ratios (8)
      - debt_to_equity: Numeric
      - debt_to_assets: Numeric
      - debt_to_capital: Numeric
      - equity_ratio: Numeric
      - interest_coverage: Numeric
      - debt_service_coverage: Numeric
      - cash_flow_to_debt: Numeric
      - long_term_debt_to_equity: Numeric

      # Efficiency Ratios (10)
      - inventory_turnover: Numeric
      - receivables_turnover: Numeric
      - payables_turnover: Numeric
      - fixed_asset_turnover: Numeric
      - total_asset_turnover: Numeric
      - working_capital_turnover: Numeric
      - revenue_per_employee: Numeric
      - asset_productivity: Numeric
      - capital_intensity: Numeric
      - operating_cycle: Numeric

      # Valuation Ratios (12)
      - pe_ratio: Numeric
      - pb_ratio: Numeric
      - ps_ratio: Numeric
      - pcf_ratio: Numeric
      - ev_to_ebitda: Numeric
      - ev_to_sales: Numeric
      - ev_to_fcf: Numeric
      - peg_ratio: Numeric
      - dividend_yield: Numeric
      - dividend_payout_ratio: Numeric
      - earnings_yield: Numeric
      - fcf_yield: Numeric

      # Growth Ratios (8)
      - revenue_growth_yoy: Numeric
      - revenue_growth_qoq: Numeric
      - earnings_growth_yoy: Numeric
      - earnings_growth_qoq: Numeric
      - eps_growth: Numeric
      - book_value_growth: Numeric
      - fcf_growth: Numeric
      - dividend_growth: Numeric
  ```

  - [ ] Create model with all 60 ratio fields
  - [ ] Add indexes
  - [ ] Add validation (ratio ranges)

- [ ] **QualityScore Model**:

  - [ ] Piotroski F-Score (0-9)
  - [ ] Altman Z-Score
  - [ ] Beneish M-Score
  - [ ] Composite quality score

- [ ] **FundamentalScore Model** (NEW):

  - [ ] Composite score (0-100)
  - [ ] Value score
  - [ ] Quality score
  - [ ] Growth score
  - [ ] Health score
  - [ ] Momentum score
  - [ ] Sector-relative scores
  - [ ] Percentile rankings

- [ ] **EarningsData Model** (NEW):

  - [ ] Earnings date
  - [ ] EPS actual/est/surprise
  - [ ] Revenue actual/est/surprise
  - [ ] Guidance

- [ ] **InsiderTransaction Model** (NEW):

  - [ ] Transaction details
  - [ ] Insider info
  - [ ] Form 4 data

- [ ] **IndustryMetrics Model** (NEW):

  - [ ] Industry aggregates
  - [ ] Peer statistics

- [ ] **ESGScore Model** (NEW):
  - [ ] E/S/G individual scores
  - [ ] Combined ESG score

#### Database Migrations

- [ ] Create Alembic migration scripts for all models
- [ ] Test migrations up/down
- [ ] Seed test data (10+ companies)

#### Configuration

- [ ] .env file with all settings
- [ ] API keys (Alpha Vantage, etc.)
- [ ] Rate limiting config
- [ ] Cache TTL settings

**Week 1 Testing**:

- [ ] Model creation tests
- [ ] Relationship tests
- [ ] Migration tests
- [ ] Validation tests

**Week 1 Success Criteria**: All models created, migrations working, test data loaded

---

### Week 2: Data Integration & Calculation Engines (Week 26)

#### Data Provider Adapters

- [ ] **AlphaVantageClient** (`app/services/data/alpha_vantage_client.py`):

  ```python
  class AlphaVantageClient:
      async def get_company_overview(symbol)
      async def get_income_statement(symbol, quarterly=False)
      async def get_balance_sheet(symbol, quarterly=False)
      async def get_cash_flow(symbol, quarterly=False)
      async def get_earnings(symbol)
      # Rate limiting: 5 calls/min (free tier)
      # Error handling: retry with exponential backoff
  ```

  - [ ] Implement all methods
  - [ ] Add rate limiting decorator
  - [ ] Add error handling
  - [ ] Add response caching
  - [ ] Add data validation
  - [ ] Test with real API

- [ ] **YahooFinanceClient** (`app/services/data/yahoo_finance_client.py`):

  - [ ] Financial statements
  - [ ] Key statistics
  - [ ] Analyst estimates
  - [ ] No rate limits
  - [ ] Fallback data source

- [ ] **FinancialModelingPrepClient** (optional premium):

  - [ ] Comprehensive fundamentals
  - [ ] Historical data (10+ years)
  - [ ] Real-time updates
  - [ ] Pre-calculated ratios

- [ ] **SECEdgarParser** (NEW):

  ```python
  class SECEdgarParser:
      async def parse_10k(cik, year)  # Annual report
      async def parse_10q(cik, year, quarter)  # Quarterly
      async def parse_8k(cik, filing_date)  # Current events
      async def extract_financial_tables(filing)
      async def extract_text_sections(filing)
  ```

  - [ ] EDGAR API integration
  - [ ] HTML/XBRL file parsing
  - [ ] Financial table extraction
  - [ ] Key metrics extraction

- [ ] **InsiderTradingClient** (NEW):
  ```python
  class InsiderTradingClient:
      async def get_form4_filings(symbol, start_date, end_date)
      async def parse_form4_xml(filing_url)
      async def get_insider_summary(symbol)
  ```
  - [ ] SEC EDGAR Form 4 API
  - [ ] XML parsing
  - [ ] Transaction extraction
  - [ ] Aggregation logic

#### Data Ingestion Service

- [ ] **DataIngestionService** (`app/services/data/ingestion_service.py`):
  ```python
  class DataIngestionService:
      async def fetch_company_data(symbol, force_refresh=False)
      async def fetch_financial_statements(symbol, period_type)
      async def fetch_earnings_data(symbol)
      async def fetch_insider_data(symbol)
      async def batch_fetch(symbols: List[str])
      async def incremental_update(symbol)  # Only new data
  ```
  - [ ] Implement all methods
  - [ ] Multi-source fallback logic
  - [ ] Batch processing (concurrent)
  - [ ] Incremental updates
  - [ ] Data validation pipeline
  - [ ] Duplicate detection
  - [ ] Data quality scoring
  - [ ] Store in PostgreSQL
  - [ ] Cache in Redis (24h TTL)

#### Core Calculation Engines

- [ ] **RatioCalculator** (`app/services/calculator/ratio_calculator.py`):

  ```python
  class RatioCalculator:
      # Liquidity (10 methods)
      def calculate_current_ratio(current_assets, current_liabilities)
      def calculate_quick_ratio(current_assets, inventory, current_liabilities)
      def calculate_cash_ratio(cash, current_liabilities)
      # ... all 10 liquidity ratios

      # Profitability (12 methods)
      def calculate_gross_profit_margin(gross_profit, revenue)
      def calculate_net_profit_margin(net_income, revenue)
      def calculate_roe(net_income, shareholders_equity)
      # ... all 12 profitability ratios

      # Leverage (8 methods)
      # Efficiency (10 methods)
      # Valuation (12 methods)
      # Growth (8 methods)

      def calculate_all_ratios(financial_data, previous_data):
          # Calculate all 60 ratios
          # Return dictionary
  ```

  - [ ] Implement all 60 ratio calculations
  - [ ] Add null handling
  - [ ] Add division by zero protection
  - [ ] Add validation (reasonable ranges)
  - [ ] Unit test each ratio
  - [ ] Validate against Bloomberg data

- [ ] **ValuationCalculator** (`app/services/calculator/valuation_calculator.py`):

  ```python
  class ValuationCalculator:
      def calculate_dcf_valuation(fcf, growth_rate, discount_rate, years)
      def calculate_ddm_valuation(dividend, growth_rate, required_return)
      def calculate_graham_number(eps, book_value_per_share)
      def calculate_peg_ratio(pe_ratio, earnings_growth_rate)
      def calculate_ev_multiples(enterprise_value, ebitda, sales, fcf)
      def calculate_fair_value_estimate(financial_data, market_data, assumptions)
  ```

  - [ ] Implement all valuation models
  - [ ] Add sensitivity analysis
  - [ ] Add confidence intervals
  - [ ] Create weighted fair value
  - [ ] Calculate margin of safety

- [ ] **QualityCalculator** (`app/services/calculator/quality_calculator.py`):

  ```python
  class QualityCalculator:
      def calculate_piotroski_f_score(financial_data):
          # 9-point scoring system
          # Profitability (4 points)
          # Leverage/Liquidity (3 points)
          # Operating Efficiency (2 points)

      def calculate_altman_z_score(wc, assets, re, ebit, mkt_cap, liabilities, sales):
          # Bankruptcy prediction
          # Z = 1.2X1 + 1.4X2 + 3.3X3 + 0.6X4 + 1.0X5
          # Z > 2.99: Safe
          # 1.81 < Z < 2.99: Grey zone
          # Z < 1.81: Distress

      def calculate_beneish_m_score(financial_ratios):
          # Earnings manipulation detection
          # M = -4.84 + 0.92*DSRI + 0.528*GMI + ...
          # M > -2.22: Likely manipulator
  ```

  - [ ] Implement all quality scores
  - [ ] Add score interpretation
  - [ ] Add historical tracking

- [ ] **CompositeScorer** (NEW) (`app/services/calculator/composite_scorer.py`):
  ```python
  class CompositeScorer:
      def calculate_value_score(valuation_ratios, sector_avg):
          # PE, PB, PS relative to sector
          # 0-100 scale

      def calculate_quality_score(f_score, z_score, m_score):
          # Weighted combination
          # 0-100 scale

      def calculate_growth_score(growth_rates, sector_avg):
          # Revenue, earnings, FCF growth
          # 0-100 scale

      def calculate_health_score(financial_health_metrics):
          # Liquidity, solvency, profitability
          # 0-100 scale

      def calculate_momentum_score(fundamental_trends):
          # Improving/deteriorating fundamentals
          # 0-100 scale

      def calculate_composite_score(all_scores):
          # Weighted average
          # Value: 20%, Quality: 25%, Growth: 20%
          # Health: 20%, Momentum: 15%
          # Final score: 0-100

      def calculate_sector_relative_score(score, sector_scores):
          # Percentile within sector

      def calculate_percentile_rank(score, all_scores):
          # Percentile across all stocks
  ```
  - [ ] Implement all scoring methods
  - [ ] Add weighting configuration
  - [ ] Add sector normalization
  - [ ] Test scoring accuracy

#### Calculation Service

- [ ] **CalculationService** (`app/services/calculator/calculation_service.py`):
  ```python
  class CalculationService:
      async def calculate_company_fundamentals(company_id, period)
      async def calculate_batch(company_ids: List[UUID])
      async def recalculate_on_data_update(company_id)
      async def schedule_periodic_calculation()  # Daily for all
  ```
  - [ ] Orchestrate all calculations
  - [ ] Async batch processing
  - [ ] Cache results
  - [ ] Error handling
  - [ ] Performance monitoring

**Week 2 Testing**:

- [ ] Data provider tests (mocked APIs)
- [ ] Data ingestion tests
- [ ] Each ratio calculation test
- [ ] Valuation model tests
- [ ] Quality score tests
- [ ] Composite score tests
- [ ] Performance tests (100 companies <5s)
- [ ] Accuracy validation (vs Bloomberg)

**Week 2 Success Criteria**: All calculators working, all ratios accurate, composite scoring operational

---

### Week 3: Advanced Analyzers & Alert System (Week 27)

#### Earnings Analyzer (NEW)

- [ ] **EarningsAnalyzer** (`app/services/analyzers/earnings_analyzer.py`):
  ```python
  class EarningsAnalyzer:
      async def get_earnings_calendar(days_ahead=30)
      async def get_earnings_history(symbol, quarters=8)
      async def calculate_earnings_surprise(actual, estimate)
      async def calculate_surprise_consistency(history)
      async def analyze_earnings_quality(financial_statements)
      async def forecast_iv_expansion(symbol, historical_earnings)
      async def predict_post_earnings_move(symbol, surprise, iv)
      async def analyze_guidance(symbol, earnings_data)
  ```
  - [ ] Earnings calendar integration
  - [ ] Earnings surprise calculation
  - [ ] Historical pattern analysis
  - [ ] IV forecasting model
  - [ ] Post-earnings move prediction
  - [ ] Quality metrics
  - [ ] Guidance tracking

#### Insider Analyzer (NEW)

- [ ] **InsiderAnalyzer** (`app/services/analyzers/insider_analyzer.py`):
  ```python
  class InsiderAnalyzer:
      async def track_insider_transactions(symbol, period_days=90)
      async def calculate_insider_sentiment(transactions)
      async def detect_insider_clusters(transactions)
      async def weight_by_position(insider_title, transaction_value)
      async def identify_unusual_activity(symbol, transactions)
      async def check_blackout_periods(transactions, earnings_dates)
  ```
  - [ ] Form 4 monitoring
  - [ ] Transaction parsing
  - [ ] Sentiment scoring (-100 to +100)
  - [ ] Cluster detection (3+ insiders buying)
  - [ ] Position weighting (CEO=3x, CFO=2x, Director=1x)
  - [ ] Unusual activity alerts

#### Industry Analyzer (NEW)

- [ ] **IndustryAnalyzer** (`app/services/analyzers/industry_analyzer.py`):
  ```python
  class IndustryAnalyzer:
      async def calculate_sector_momentum(sector)
      async def identify_sector_rotation_signals()
      async def calculate_sector_lifecycle_position(sector)
      async def analyze_competitive_position(symbol, peers)
      async def calculate_market_share(symbol, industry_data)
      async def identify_peer_companies(symbol)
      async def calculate_peer_statistics(peer_data)
      async def calculate_percentile_ranking(symbol, peers, metric)
  ```
  - [ ] Sector rotation indicators
  - [ ] Lifecycle analysis (growth/mature/decline)
  - [ ] Competitive position scoring
  - [ ] Peer identification (auto)
  - [ ] Peer comparison
  - [ ] Market share analysis
  - [ ] Percentile rankings

#### Health Monitor (NEW)

- [ ] **HealthMonitor** (`app/services/analyzers/health_monitor.py`):
  ```python
  class HealthMonitor:
      async def monitor_financial_health(symbol)
      async def detect_early_warnings(symbol, thresholds)
      async def predict_bankruptcy_risk(symbol, financial_data)
      async def calculate_credit_risk_score(symbol)
      async def track_covenant_compliance(symbol, debt_covenants)
      async def generate_health_dashboard(symbol)
  ```
  - [ ] Early warning indicators
    - [ ] Deteriorating margins (>10% decline)
    - [ ] Rising debt (>20% increase)
    - [ ] Declining liquidity (current ratio <1.0)
    - [ ] Negative cash flow (3 consecutive quarters)
  - [ ] Bankruptcy prediction
    - [ ] Altman Z-Score tracking
    - [ ] Ohlson O-Score
    - [ ] Zmijewski Score
  - [ ] Credit risk scoring
  - [ ] Health score (0-100)

#### ESG Analyzer (NEW - Optional)

- [ ] **ESGAnalyzer** (`app/services/analyzers/esg_analyzer.py`):
  - [ ] ESG score integration (API)
  - [ ] Environmental metrics
  - [ ] Social metrics
  - [ ] Governance metrics
  - [ ] ESG trend analysis

#### Alert System

- [ ] **AlertService** (`app/services/alerts/alert_service.py`):

  ```python
  class AlertService:
      async def create_alert(alert_config)
      async def check_triggers()  # Run every 15 minutes
      async def send_alert(alert)
      async def manage_user_preferences(user_id)
  ```

  **Alert Types**:

  - [ ] Earnings date reminder (7 days, 1 day, day-of)
  - [ ] Ratio threshold (e.g., ROE >0.2)
  - [ ] Quality score change (F-Score increased)
  - [ ] Composite score change (>5 point move)
  - [ ] Insider cluster (3+ insiders buying)
  - [ ] Health Score deterioration (<50)
  - [ ] Peer comparison (fell below 25th percentile)
  - [ ] Sector rotation signal

  **Delivery Channels**:

  - [ ] Kafka events (fundamental.alert.{symbol})
  - [ ] Email (SMTP/SendGrid)
  - [ ] Push notifications
  - [ ] Trading journal integration

**Week 3 Testing**:

- [ ] Earnings analyzer tests
- [ ] Insider analyzer tests
- [ ] Industry analyzer tests
- [ ] Health monitor tests
- [ ] ESG analyzer tests (if implemented)
- [ ] Alert trigger tests
- [ ] Alert delivery tests
- [ ] Integration tests

**Week 3 Success Criteria**: All analyzers operational, alerts triggering and delivering correctly

---

### Week 4: Integration, API & Comprehensive Testing (Week 28)

#### Kafka Integration

- [ ] **Event Schemas** (Schema Registry):

  ```avro
  // fundamental.score.{symbol}
  {
    "type": "record",
    "name": "FundamentalScore",
    "fields": [
      {"name": "symbol", "type": "string"},
      {"name": "timestamp", "type": "long"},
      {"name": "composite_score", "type": "int"},
      {"name": "value_score", "type": "int"},
      {"name": "quality_score", "type": "int"},
      {"name": "growth_score", "type": "int"},
      {"name": "health_score", "type": "int"},
      {"name": "momentum_score", "type": "int"},
      {"name": "sector_relative_score", "type": "int"},
      {"name": "percentile_rank", "type": "int"},
      {
        "name": "quality_scores",
        "type": {
          "type": "record",
          "fields": [
            {"name": "piotroski_f_score", "type": "int"},
            {"name": "altman_z_score", "type": "double"},
            {"name": "beneish_m_score", "type": "double"}
          ]
        }
      },
      {
        "name": "key_ratios",
        "type": {
          "type": "record",
          "fields": [
            {"name": "pe_ratio", "type": ["null", "double"]},
            {"name": "pb_ratio", "type": ["null", "double"]},
            {"name": "roe", "type": ["null", "double"]},
            {"name": "debt_to_equity", "type": ["null", "double"]},
            {"name": "current_ratio", "type": ["null", "double"]},
            {"name": "profit_margin", "type": ["null", "double"]}
          ]
        }
      },
      {
        "name": "fair_value",
        "type": {
          "type": "record",
          "fields": [
            {"name": "dcf", "type": ["null", "double"]},
            {"name": "ddm", "type": ["null", "double"]},
            {"name": "graham", "type": ["null", "double"]},
            {"name": "avg_fair_value", "type": "double"},
            {"name": "current_price", "type": "double"},
            {"name": "upside_percentage", "type": "double"},
            {"name": "margin_of_safety", "type": "double"}
          ]
        }
      },
      {"name": "recommendation", "type": {"type": "enum", "symbols": ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]}},
      {"name": "confidence", "type": "double"}
    ]
  }

  // fundamental.alert.{symbol}
  {
    "type": "record",
    "name": "FundamentalAlert",
    "fields": [
      {"name": "symbol", "type": "string"},
      {"name": "alert_type", "type": "string"},
      {"name": "severity", "type": {"type": "enum", "symbols": ["INFO", "WARNING", "CRITICAL"]}},
      {"name": "message", "type": "string"},
      {"name": "details", "type": ["null", "string"]},
      {"name": "timestamp", "type": "long"}
    ]
  }
  ```

  - [ ] Define all event schemas
  - [ ] Register with Schema Registry
  - [ ] Version schemas

- [ ] **Event Publishing**:

  - [ ] Publish score updates after calculation
  - [ ] Publish alerts when triggered
  - [ ] Publish data quality events
  - [ ] Batch publishing (100 events/batch)
  - [ ] Error handling & DLQ

- [ ] **Event Consumption**:
  - [ ] Subscribe to symbol.added (trigger fetch)
  - [ ] Subscribe to price.updated (trigger recalc if needed)

#### REST API Endpoints

- [ ] **Company Fundamentals Group**:

  ```python
  @router.get("/api/v1/fundamental/{symbol}")
  async def get_company_fundamentals(symbol: str)

  @router.get("/api/v1/fundamental/{symbol}/ratios")
  async def get_financial_ratios(symbol: str, period: str = "annual")

  @router.get("/api/v1/fundamental/{symbol}/valuation")
  async def get_valuation_models(symbol: str)

  @router.get("/api/v1/fundamental/{symbol}/quality-scores")
  async def get_quality_scores(symbol: str)

  @router.get("/api/v1/fundamental/{symbol}/composite-score")
  async def get_composite_score(symbol: str)

  @router.get("/api/v1/fundamental/{symbol}/history")
  async def get_fundamental_history(symbol: str, periods: int = 8)
  ```

- [ ] **Screening Group**:

  ```python
  @router.post("/api/v1/fundamental/screen")
  async def screen_stocks(filters: ScreenFilters)
  # Example filters:
  # {
  #   "min_roe": 0.15,
  #   "max_pe": 20,
  #   "min_f_score": 7,
  #   "min_composite_score": 70,
  #   "min_health_score": 60,
  #   "sectors": ["Technology", "Healthcare"]
  # }

  @router.get("/api/v1/fundamental/top-scored/{sector}")
  async def get_top_scored_stocks(sector: str, limit: int = 20)

  @router.get("/api/v1/fundamental/undervalued")
  async def get_undervalued_stocks(min_upside: float = 0.15)
  ```

- [ ] **Earnings Group**:

  ```python
  @router.get("/api/v1/fundamental/earnings-calendar")
  async def get_earnings_calendar(days_ahead: int = 30)

  @router.get("/api/v1/fundamental/{symbol}/earnings")
  async def get_earnings_data(symbol: str)

  @router.get("/api/v1/fundamental/{symbol}/earnings-history")
  async def get_earnings_history(symbol: str, quarters: int = 8)
  ```

- [ ] **Insider Group**:

  ```python
  @router.get("/api/v1/fundamental/{symbol}/insider-transactions")
  async def get_insider_transactions(symbol: str, days: int = 90)

  @router.get("/api/v1/fundamental/{symbol}/insider-sentiment")
  async def get_insider_sentiment(symbol: str)
  ```

- [ ] **Industry Group**:

  ```python
  @router.get("/api/v1/fundamental/industry/{industry}/metrics")
  async def get_industry_metrics(industry: str)

  @router.get("/api/v1/fundamental/{symbol}/peer-comparison")
  async def get_peer_comparison(symbol: str)
  ```

- [ ] **Alert Group**:

  ```python
  @router.get("/api/v1/fundamental/alerts")
  async def get_user_alerts()

  @router.post("/api/v1/fundamental/alerts")
  async def create_alert(alert_config: AlertConfig)

  @router.delete("/api/v1/fundamental/alerts/{alert_id}")
  async def delete_alert(alert_id: UUID)
  ```

- [ ] Add JWT authentication to all endpoints
- [ ] Add rate limiting (100 req/min per user)
- [ ] Add response caching
- [ ] Add pagination (limit/offset)
- [ ] Add filtering and sorting
- [ ] Generate OpenAPI documentation

#### Integration with Other Services

- [ ] **Market Scanner Integration**:

  ```python
  # Add fundamental filters to scanner
  fundamental_filters = [
      "min_roe", "max_pe", "min_f_score",
      "min_composite_score", "min_health_score"
  ]

  # Combined scan example:
  # Technical: RSI < 30 (oversold)
  # Fundamental: ROE > 0.15, F-Score > 7, Composite > 70
  ```

  - [ ] Export fundamental filters
  - [ ] Combined technical + fundamental scans
  - [ ] Top fundamental picks feed

- [ ] **Options Trading Integration**:

  ```python
  # Earnings calendar for earnings plays
  # IV forecasting for option pricing
  # Fundamental score for stock selection
  ```

  - [ ] Earnings calendar API
  - [ ] IV expansion forecasting
  - [ ] Fundamental score for option strategies

- [ ] **AI Strategy Development Integration**:

  - [ ] Add fundamental signals to Blockly
  - [ ] Fundamental indicator blocks
  - [ ] Combined strategy templates

- [ ] **Trading Journal Integration**:
  - [ ] Log fundamental scores at trade entry
  - [ ] Track fundamental changes during hold
  - [ ] Post-trade fundamental analysis

#### Caching Strategy

- [ ] **Redis Caching**:
  ```python
  # Cache keys and TTLs
  caches = {
      "ratios:{symbol}": "24h",
      "valuation:{symbol}": "24h",
      "composite_score:{symbol}": "1h",
      "earnings_calendar": "6h",
      "insider_sentiment:{symbol}": "4h",
      "peer_comparison:{symbol}": "12h",
      "top_scored:{sector}": "30m"
  }
  ```
  - [ ] Implement cache decorator
  - [ ] Cache warming (popular symbols)
  - [ ] Cache invalidation on new data
  - [ ] Cache hit ratio monitoring

#### Comprehensive Testing

**Unit Tests** (>95% coverage):

- [ ] All calculator tests (60 ratios)
- [ ] All data provider tests (mocked)
- [ ] All analyzer tests
- [ ] All model tests
- [ ] All API endpoint tests
- [ ] All service tests

**Integration Tests**:

- [ ] End-to-end data flow
  - [ ] Fetch → Process → Calculate → Store → Publish
- [ ] Multi-service integration
  - [ ] Fundamental + Market Scanner
  - [ ] Fundamental + Options
- [ ] Kafka event flow
- [ ] Database integration
- [ ] Cache integration

**Performance Tests**:

- [ ] Single company calc <10ms
- [ ] Batch (100 companies) <5s
- [ ] API response <200ms (p95)
- [ ] Concurrent users (100+)
- [ ] Kafka throughput (1000 events/sec)

**Accuracy Tests**:

- [ ] Validate ratios vs Bloomberg
- [ ] Validate valuations vs analyst estimates
- [ ] Validate quality scores vs research
- [ ] Historical accuracy backtest
- [ ] Cross-check calculations

**Security Tests**:

- [ ] Authentication tests
- [ ] Authorization tests
- [ ] SQL injection prevention
- [ ] Data validation
- [ ] Rate limiting

**Data Quality Tests**:

- [ ] Missing data handling
- [ ] Outlier detection
- [ ] Data consistency checks
- [ ] Source comparison

**Week 4 Testing**: All comprehensive testing as described

**Week 4 Success Criteria**:

- > 95% test coverage
- All tests passing
- API documented (OpenAPI)
- Kafka integration working
- Performance benchmarks met
- Zero critical bugs

---

**Phase 15.5 Complete Deliverables**:
✅ Fundamental analysis microservice operational  
✅ All 60 financial ratios calculating accurately  
✅ 5 valuation models working (DCF, DDM, Graham, PEG, EV)  
✅ 3 quality scores operational (F-Score, Z-Score, M-Score)  
✅ Composite scoring system (0-100 scale)  
✅ Earnings analyzer with IV forecasting  
✅ Insider transaction tracking and sentiment  
✅ Industry and peer analysis  
✅ Financial health monitoring  
✅ Alert system with multi-channel delivery  
✅ Kafka integration complete (score + alert events)  
✅ REST API with 20+ endpoints documented  
✅ Integration with Market Scanner ready  
✅ Integration with Options Trading ready  
✅ >95% test coverage achieved  
✅ Performance benchmarks met  
✅ Production-ready code quality

---

## Phase 16: Market Scanner Service (Week 29) - Enhanced

**Enhanced Features from v4.0**:

- ✅ Fundamental filters integration
- ✅ Combined technical + fundamental scans
- ✅ Multi-factor screening

**Tasks**:

### Core Scanner Implementation

- [ ] Real-time scanning engine (Python + Redis)
- [ ] Technical indicator filters (50+ indicators)
- [ ] **Fundamental filters integration** (NEW):
  - [ ] ROE, ROA, ROIC filters
  - [ ] P/E, P/B, P/S filters
  - [ ] Debt/Equity filters
  - [ ] F-Score filters
  - [ ] Composite score filters
  - [ ] Health score filters
- [ ] Pattern recognition module
- [ ] Scan result caching
- [ ] Real-time updates via WebSocket

### Combined Scanning (NEW)

- [ ] **Multi-Factor Scans**:
  ```python
  # Example: Value + Technical Oversold
  filters = {
      "technical": {"rsi_14": {"max": 30}},  # Oversold
      "fundamental": {
          "pe_ratio": {"max": 15},  # Undervalued
          "roe": {"min": 0.15},  # Quality
          "f_score": {"min": 7}  # Strong fundamentals
      }
  }
  ```
- [ ] Top fundamental picks feed
- [ ] Earnings gap scanner (fundamental + price action)

### UI Integration

- [ ] Scan configuration UI
- [ ] Real-time results grid
- [ ] Filter builder (drag-and-drop)
- [ ] Saved scans
- [ ] Alert on scan results

**Testing**:

- Scanner performance tests
- Filter accuracy tests
- Combined scan tests
- Real-time update tests

**Success Criteria**: Scanner operational with fundamental filters, <1s scan time for 500 stocks

---

[Continue with remaining phases 16.5-27 following same detailed pattern...]

## Summary Statistics

**Total Phases**: 28  
**Total Weeks**: 55 (42 development + 13 paper trading)  
**Total Tasks**: 800+  
**New in v5.0**: Phase 15.5 (Fundamental Analysis, 4 weeks)  
**Test Coverage Required**: >95%  
**Deployment Options**: 3 (Laptop-only → Hybrid → Cloud optional)

---

**Document Version**: 5.0  
**Status**: Ready for Implementation  
**Review Schedule**: Weekly during development  
**Maintained By**: Trading System Team
