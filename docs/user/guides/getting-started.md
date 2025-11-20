# Getting Started Guide

## Agentic AI Algorithmic Trading System v5.0

**Welcome!** This guide will have you up and running in **15 minutes**.

---

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Installation](#installation)
3. [First Login](#first-login)
4. [Creating Your First Strategy](#creating-your-first-strategy)
5. [Deploying to Paper Trading](#deploying-to-paper-trading)
6. [Monitoring Performance](#monitoring-performance)
7. [Next Steps](#next-steps)
8. [Troubleshooting](#troubleshooting)

---

## System Requirements

### Minimum Requirements

- **OS**: Windows 10/11, macOS 12+, or Linux (Ubuntu 20.04+)
- **RAM**: 32GB (recommended: 64GB)
- **Disk Space**: 100GB SSD
- **CPU**: 8 cores (recommended: 12+ cores)
- **Internet**: Stable broadband connection
- **Docker**: Docker Desktop 24.0+

### Optional for ML/DL Features

- **GPU**: NVIDIA RTX 3060 or better
- **VRAM**: 6GB+ (for LSTM/RL training)
- **CUDA**: 12.6+
- **NVIDIA Container Toolkit**: Latest

### Software Prerequisites

- **Docker Desktop** (Windows/Mac) or Docker Engine (Linux)
- **WSL2** (Windows only)
- **Python** 3.11+ (for CLI tools)
- **Git** (for version control)

---

## Installation

### Step 1: Clone Repository

```bash
# Clone the repository
git clone https://github.com/yourusername/IBKR-Algo-Trader.git

# Navigate to directory
cd "IBKR - Algo Trader"
```

### Step 2: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your API keys
# Required:
#   - ALPHA_VANTAGE_API_KEY (free tier: https://www.alphavantage.co/support/#api-key)
# Optional:
#   - FINANCIAL_MODELING_PREP_API_KEY (premium features)
#   - IBKR credentials (for live trading)
```

**Quick .env Setup**:

```bash
# Open .env in your editor
nano .env  # or: code .env (VS Code) / notepad .env (Windows)

# Minimum configuration:
ALPHA_VANTAGE_API_KEY=your_key_here
POSTGRES_PASSWORD=your_secure_password
KEYCLOAK_ADMIN_PASSWORD=your_admin_password
```

> 💡 **Tip**: Get a free Alpha Vantage API key at https://www.alphavantage.co/support/#api-key (takes 30 seconds)

### Step 3: Start Infrastructure

```bash
# Start all services (28 microservices + 5 databases)
docker-compose up -d

# This will take 5-10 minutes on first run
# Docker will download images (~15GB total)
```

**What's Being Started**:

- ✅ PostgreSQL 17 (transactional database)
- ✅ ClickHouse 24.8 (time-series analytics)
- ✅ Neo4j 5.25 (knowledge graph)
- ✅ Redis 7.4 (caching)
- ✅ Qdrant 1.12 (vector database)
- ✅ Apache Kafka 3.9 (event bus)
- ✅ Keycloak 26.0 (authentication)
- ✅ 28 Microservices (trading, analysis, AI, etc.)

### Step 4: Verify Installation

```bash
# Check all services are running
docker-compose ps

# Expected output: All services should show "Up" or "running"
# If any service shows "Exit" or "Restarting", see Troubleshooting section
```

**Quick Health Check**:

```bash
# Check API Gateway
curl http://localhost:8000/health

# Expected: {"status": "healthy", "version": "1.0.0"}
```

### Step 5: Access the Platform

Open your browser and navigate to:

- **Web UI**: http://localhost:3000
- **API Gateway**: http://localhost:8000
- **Grafana Dashboard**: http://localhost:3001
  - Username: `admin`
  - Password: Check `docker-compose.yml` or set in `.env`

---

## First Login

### Creating Your Account

1. Navigate to http://localhost:3000
2. Click **"Sign Up"**
3. Fill in:
   - Email address
   - Password (min 12 characters, include uppercase, lowercase, number, symbol)
   - Display name
4. Verify email (local development skips this)
5. Click **"Create Account"**

### Setting Up Your Profile

1. After login, go to **Settings** → **Profile**
2. Set your:
   - **Experience Level**: Beginner, Intermediate, Advanced
   - **Trading Style**: Day trading, Swing trading, Long-term
   - **Risk Tolerance**: Conservative, Moderate, Aggressive
3. This helps the AI Assistant provide personalized guidance

---

## Creating Your First Strategy

### Option 1: Using a Template (Recommended for Beginners)

1. Navigate to **Strategies** → **Create New**
2. Click **"Use Template"**
3. Select **"Simple Momentum Strategy"**
4. Review the pre-filled code:

```python
from libs.common.strategy import BaseStrategy

class SimpleMomentumStrategy(BaseStrategy):
    """
    Simple momentum strategy using RSI indicator.
    - Buy when RSI < 30 (oversold)
    - Sell when RSI > 70 (overbought)
    """

    def __init__(self, period=14, oversold=30, overbought=70):
        super().__init__()
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def on_bar(self, bar):
        # Calculate RSI
        rsi = self.indicators.rsi(symbol=bar.symbol, period=self.period)

        # Entry signal
        if rsi < self.oversold and not self.has_position(bar.symbol):
            self.buy(symbol=bar.symbol, quantity=100)

        # Exit signal
        elif rsi > self.overbought and self.has_position(bar.symbol):
            self.sell(symbol=bar.symbol, quantity=100)
```

5. Customize parameters if desired:

   - `period`: RSI lookback period (default: 14)
   - `oversold`: Oversold threshold (default: 30)
   - `overbought`: Overbought threshold (default: 70)

6. Click **"Save Strategy"**

### Option 2: Using Visual Builder (Blockly)

1. Navigate to **Strategies** → **Create New** → **Visual Builder**
2. Drag and drop blocks:
   - **Indicator**: RSI (14-period)
   - **Condition**: If RSI < 30
   - **Action**: Buy 100 shares
   - **Condition**: If RSI > 70
   - **Action**: Sell 100 shares
3. Click **"Generate Code"** to see Python equivalent
4. Click **"Save Strategy"**

### Option 3: Ask AI Assistant

1. Click **AI Assistant** in the sidebar
2. Type: _"Create a simple momentum strategy using RSI"_
3. AI will generate strategy code and explain it
4. Review and click **"Use This Strategy"**

---

## Deploying to Paper Trading

> ⚠️ **Important**: Always test in paper trading before live trading. Minimum 90 days recommended.

### Backtesting First (Recommended)

Before deploying to paper trading, backtest your strategy:

1. Go to **Strategies** → Select your strategy
2. Click **"Backtest"**
3. Configure:
   - **Symbols**: Enter comma-separated tickers (e.g., `AAPL, MSFT, GOOGL`)
   - **Start Date**: 2 years ago recommended
   - **End Date**: Today
   - **Initial Capital**: $10,000
   - **Commission**: $0.005/share (IBKR default)
4. Click **"Run Backtest"**
5. Review results:
   - Total Return
   - Sharpe Ratio (>1.0 good, >2.0 excellent)
   - Max Drawdown (<20% good)
   - Win Rate
6. If satisfactory, proceed to paper trading

### Deploying to Paper Trading

1. Go to **Strategies** → Select your strategy
2. Click **"Deploy"**
3. Select **"Paper Trading"** mode
4. Configure:
   - **Capital Allocation**: $10,000 (virtual money)
   - **Symbols to Trade**: AAPL, MSFT, GOOGL
   - **Risk Limits**:
     - Max position size: 10% of capital
     - Max daily loss: 2%
     - Max drawdown: 15%
5. Review configuration
6. Click **"Deploy to Paper Trading"**
7. Confirm deployment

**Deployment Checklist**:

- ✅ Strategy backtested with positive results
- ✅ Risk limits configured
- ✅ Realistic capital allocation
- ✅ Symbols carefully selected
- ✅ Paper trading mode confirmed (not live!)

---

## Monitoring Performance

### Real-Time Dashboard

After deployment, monitor your strategy:

1. Navigate to **Dashboard**
2. View real-time metrics:
   - **Equity Curve**: Visual performance over time
   - **Open Positions**: Current holdings
   - **Recent Trades**: Latest buy/sell executions
   - **P&L**: Profit and loss (unrealized + realized)
   - **Key Metrics**:
     - Total return
     - Sharpe ratio
     - Max drawdown
     - Win rate

### Setting Up Alerts

1. Go to **Settings** → **Notifications**
2. Configure alerts:
   - **Trade Executed**: Get notified on every trade
   - **Daily Summary**: End-of-day performance report
   - **Risk Limit Breach**: Immediate alert if limits exceeded
   - **Strategy Error**: Alert when strategy encounters error
3. Choose notification channels:
   - ✅ Email
   - ✅ Push notifications (web browser)
   - ✅ Slack (optional)
   - ✅ Discord (optional)
   - ✅ Telegram (optional)

### Performance Review

**Daily Review** (5 minutes):

- Check dashboard for today's trades
- Review P&L
- Ensure risk limits not breached

**Weekly Review** (20 minutes):

- Analyze equity curve trend
- Review win rate and profit factor
- Check if strategy is performing as expected
- Compare to backtest results

**Monthly Review** (1 hour):

- In-depth performance analysis
- Strategy optimization if needed
- Decide: continue, modify, or stop strategy

---

## Next Steps

### After Your First Week

Once comfortable with the basics, explore:

1. **Fundamental Analysis** → See [Fundamental Analysis Guide](fundamental-analysis.md)

   - Screen stocks using 50+ financial ratios
   - Combine technical + fundamental signals
   - Quality score-based position sizing

2. **Advanced Strategies** → See [Strategy Development Guide](strategy-development.md)

   - Multi-factor strategies
   - Options trading strategies
   - ML/DL-powered strategies

3. **AI Assistant** → See [AI Assistant Guide](ai-assistant-guide.md)

   - Natural language strategy creation
   - Intelligent market analysis
   - Personalized guidance

4. **Live Trading Preparation** → See [Live Trading Guide](live-trading-preparation.md)
   - When you're ready (minimum 90 days paper trading)
   - IBKR account setup
   - Risk management for real money

### Recommended Learning Path

**Week 1-2**: Getting Started

- ✅ Complete this guide
- ✅ Create 2-3 simple strategies
- ✅ Deploy to paper trading
- ✅ Monitor daily

**Week 3-4**: Understanding Fundamentals

- Learn fundamental analysis
- Create multi-factor strategies
- Understand quality scores

**Week 5-8**: Advanced Techniques

- Options trading
- Portfolio optimization
- AI-assisted strategy development

**Week 9-12**: Preparation for Live

- Review paper trading performance
- Refine strategies
- Set up IBKR account

---

## Troubleshooting

### Services Won't Start

**Issue**: `docker-compose up -d` fails

**Solutions**:

```bash
# 1. Check Docker is running
docker --version

# 2. Check system resources
docker system df  # Should have >50GB available

# 3. Restart Docker Desktop (Windows/Mac)
# Or restart Docker service (Linux): sudo systemctl restart docker

# 4. Try again with logs
docker-compose up
# Watch for error messages
```

### Can't Access Web UI

**Issue**: http://localhost:3000 not loading

**Solutions**:

```bash
# 1. Check frontend service status
docker-compose ps frontend

# 2. Check logs
docker-compose logs frontend

# 3. Verify port not in use
netstat -an | grep 3000  # Should show Docker listening

# 4. Try different port (edit docker-compose.yml)
# Change: "3000:3000" → "3001:3000"
```

### API Key Errors

**Issue**: "Invalid API key" errors in logs

**Solutions**:

1. Verify `.env` file has correct Alpha Vantage API key
2. Check key is active: https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol=AAPL&interval=5min&apikey=YOUR_KEY
3. Free tier has 5 calls/minute limit - wait if exceeded

### Database Connection Errors

**Issue**: Services can't connect to databases

**Solutions**:

```bash
# 1. Check all databases are running
docker-compose ps postgres clickhouse neo4j redis qdrant

# 2. Restart databases
docker-compose restart postgres clickhouse neo4j redis qdrant

# 3. Check database logs
docker-compose logs postgres
```

### GPU Not Detected (Optional ML Features)

**Issue**: ML services not using GPU

**Solutions**:

```bash
# 1. Verify NVIDIA driver installed
nvidia-smi

# 2. Check NVIDIA Container Toolkit
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi

# 3. Restart Docker after installing toolkit
```

### Performance Issues

**Issue**: System slow or laggy

**Solutions**:

1. **Increase Docker memory**: Docker Desktop → Settings → Resources → Memory (set to 16GB+)
2. **Close unused services**: Edit `docker-compose.yml` to disable optional services
3. **Check CPU usage**: `docker stats` - identify resource-hungry services
4. **Restart services**: `docker-compose restart`

### Still Having Issues?

- 📖 Check [Troubleshooting Guide](../troubleshooting/common-errors.md)
- ❓ Search [FAQ](../../faq/)
- 🐛 Open issue on GitHub
- 💬 Ask in Discussions

---

## Congratulations! 🎉

You've completed the getting started guide. You now have:

- ✅ System installed and running
- ✅ Account created
- ✅ First strategy deployed to paper trading
- ✅ Performance monitoring set up

**Ready to dive deeper?** Check out:

- [Fundamental Analysis Guide](fundamental-analysis.md) - Learn to use 50+ financial ratios
- [Strategy Development Guide](strategy-development.md) - Create advanced multi-factor strategies
- [Best Practices](../../best-practices.md) - Avoid common pitfalls

**Happy trading! 📈**

---

_Last Updated: 2025-11-20 | Version: 5.0_
