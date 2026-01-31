# SDLC Agent - Universal Package Installation Guide

**Version**: 2.0.0  
**Installation**: Git-based (works on any machine)  
**Interfaces**: CLI + MCP Server + Python API

---

## Quick Start

### One-Command Install

```bash
# Install from GitHub (works on any machine)
pip install git+https://github.com/VincentPereira/sdlc-agent.git
```

**That's it!** You now have:

- ✅ `sdlc` CLI command
- ✅ `sdlc-mcp-server` for IDEs
- ✅ Python API (`import sdlc_agent`)

---

## Usage

### 1. CLI Usage

```bash
# Initialize in your project
cd "C:\Users\Vincent_Pereira\Projects\Trading\IBKR - Algo Trader"
sdlc init

# Execute a phase
sdlc execute "Phase 5: Data Pipeline" --mode hybrid

# Check for updates
sdlc update --check

# Install updates
sdlc update --install

# Show status
sdlc status
```

### 2. Natural Language (in IDEs)

**In Cursor**:

```
"Use the appropriate sub agents to implement the Kafka event bus
with 3 topics, rate limiting, and >95% test coverage"
```

**In Windsurf**:

```
"Leverage SDLC agents to optimize the trading engine for <100μs latency"
```

**In Claude Code**:

```
"Please use sub agents to build the fundamental analysis service
with 50+ financial ratios"
```

### 3. Python API

```python
from sdlc_agent import get_agent_coordinator, execute_phase

# Get coordinator
coordinator = get_agent_coordinator()

# Execute phase
result = execute_phase(
    phase="Phase 5",
    mode="hybrid",
    project_root="C:/Users/.../IBKR - Algo Trader"
)
```

---

## MCP Server Setup (for IDEs)

### Cursor

Create `.cursor/mcp_servers.json`:

```json
{
  "mcpServers": {
    "sdlc-agent": {
      "command": "sdlc-mcp-server",
      "args": []
    }
  }
}
```

### Claude Desktop

Edit `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sdlc-agent": {
      "command": "sdlc-mcp-server",
      "args": []
    }
  }
}
```

### Windsurf

Similar to Cursor - add to MCP server configuration.

---

## Multi-Machine Setup

### Your Laptop (Development)

```bash
# Clone for development (editable install)
git clone https://github.com/VincentPereira/sdlc-agent.git
cd sdlc-agent
pip install -e .

# Make changes, push to GitHub
git add .
git commit -m "Enhanced Data Engineer agent"
git push
```

### Your Desktop (Usage)

```bash
# Install from GitHub
pip install git+https://github.com/VincentPereira/sdlc-agent.git

# Update when new version available
pip install --upgrade git+https://github.com/VincentPereira/sdlc-agent.git
```

### Colleague's Machine

```bash
# Just install
pip install git+https://github.com/VincentPereira/sdlc-agent.git
```

---

## Update Notifications

### Automatic (Daily)

Every time you run `sdlc`, it checks for updates (once per day):

```bash
$ sdlc execute "Phase 5"

⚠️  SDLC Agent update available!
   Installed: v2.0.0
   Latest: v2.1.0
   Update: sdlc update --install
   Changelog: https://github.com/VincentPereira/sdlc-agent/releases/tag/v2.1.0

Executing Phase 5...
```

### Manual Check

```bash
# Check for updates
$ sdlc update --check

Checking for updates...
⚠️  Update available: v2.1.0
   Run: sdlc update --install
```

### One-Command Update

```bash
# Check and install update
$ sdlc update --install

Downloading update v2.1.0...
Installing...
✅ Updated successfully!
Restart your terminal to use new version.
```

### Disable Auto-Check (Optional)

Edit `~/.sdlc/config.yaml`:

```yaml
update_notifications:
  enabled: false # Disable auto-check
```

---

## Project Configuration

### Initialize Project

```bash
cd "C:\Users\Vincent_Pereira\Projects\Trading\IBKR - Algo Trader"
sdlc init
```

This creates:

```
.sdlc/
├── config.yaml      # Project configuration
└── context/         # Project-specific knowledge
```

### Configure for IBKR Project

Edit `.sdlc/config.yaml`:

```yaml
project:
  name: "IBKR Agentic AI Algorithmic Trading System"
  type: "trading_system"

technology_stack:
  languages:
    - python
    - rust
    - typescript
  frameworks:
    - nautilus_trader
    - fastapi
    - langchain
  databases:
    - postgresql
    - clickhouse
    - neo4j
    - redis
    - qdrant
  messaging:
    - kafka

quality_gates:
  test_coverage: 95
  performance_threshold_ms: 100
  code_quality_score: 8.0

execution_mode: hybrid # full_auto, hybrid, manual
```

---

## Available Commands

| Command                 | Description                              |
| ----------------------- | ---------------------------------------- |
| `sdlc init`             | Initialize SDLC agent in current project |
| `sdlc execute <phase>`  | Execute a development phase              |
| `sdlc status`           | Show SDLC agent status                   |
| `sdlc update --check`   | Check for updates                        |
| `sdlc update --install` | Install latest update                    |
| `sdlc --version`        | Show version                             |
| `sdlc --help`           | Show help                                |

---

## MCP Server Tools

When using natural language in IDEs, these tools are available:

1. **execute_phase** - Execute complete SDLC phase
2. **implement_feature** - Implement specific feature
3. **review_code** - Comprehensive code review
4. **optimize_performance** - Performance optimization
5. **generate_tests** - Generate comprehensive tests
6. **design_architecture** - Design system architecture
7. **route_task** - Intelligently route task to agents

---

## Troubleshooting

### MCP Server Not Working

1. Verify installation:

   ```bash
   which sdlc-mcp-server
   ```

2. Test MCP server:

   ```bash
   sdlc-mcp-server
   # Should start without errors
   ```

3. Check IDE MCP configuration

### Update Check Failing

- Requires internet connection
- GitHub API rate limit (60 requests/hour)
- Disable with: `update_notifications.enabled: false`

### Command Not Found

```bash
# Reinstall
pip install --force-reinstall git+https://github.com/VincentPereira/sdlc-agent.git
```

---

## Next Steps

1. ✅ Install: `pip install git+https://github.com/VincentPereira/sdlc-agent.git`
2. ✅ Initialize: `sdlc init`
3. ✅ Configure MCP in your IDE
4. ✅ Run pilot: `sdlc execute "Phase 5: Data Pipeline"`

---

## Support

- GitHub Issues: https://github.com/VincentPereira/sdlc-agent/issues
- Documentation: https://github.com/VincentPereira/sdlc-agent/blob/main/README.md
