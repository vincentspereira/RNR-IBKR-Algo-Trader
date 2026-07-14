# SDLC Agent Package: Universal Architecture Design

**Date**: November 21, 2025  
**Version**: 1.0  
**Status**: Architecture Planning

---

## Requirements Summary

### Core Requirements

1. ✅ **Project-Agnostic**: Works in any project
2. ✅ **IDE-Agnostic**: Works in VS Code, Cursor, Windsurf, Antigravity, Trae, Kiro, etc.
3. ✅ **Extension-Agnostic**: Works with Copilot, Gemini Code Assist, Kilo Code, Roo Code, Cline, etc.
4. ✅ **CLI-Agnostic**: Works with Claude CLI, Gemini CLI, Copilot CLI, etc.
5. ✅ **Natural Language Invocation**: Like Claude Code ("use sub agents to implement...")
6. ✅ **Automatic Updates**: All projects benefit from updates
7. ✅ **Configuration**: YAML per project (`.sdlc/config.yaml`)

---

## Installation Methods: Comprehensive Comparison

### Method 1: Python Package (pip install)

#### How It Works

```bash
# One-time installation
pip install -e "/home/vincentspereira/Projects/AI Agents/Multi-Agent System/agents/agent - sdlc"

# Makes 'sdlc' command available globally
sdlc --version
```

#### Architecture

```
Python site-packages/
└── sdlc_agent/
    ├── cli/
    │   └── main.py  # Entry point for 'sdlc' command
    ├── agents/
    │   └── [21 sub-agents]
    ├── orchestration/
    └── core/

# Anywhere on your system:
$ sdlc execute --project "RNR-IBKR-Algo-Trader" --phase "Phase 5"
```

#### Pros ✅

- ✅ **Simple**: Standard Python workflow
- ✅ **Universal CLI access**: `sdlc` command works everywhere
- ✅ **Editable install**: Changes in source automatically reflected
- ✅ **Familiar**: Python developers know pip
- ✅ **Version control**: pip list, pip show sdlc-agent
- ✅ **No extra services**: Just install and use

#### Cons ❌

- ❌ **CLI-only**: Must run commands manually
- ❌ **Not IDE-integrated**: Can't use from IDE UI
- ❌ **No natural language**: Must type exact commands
- ❌ **No extension integration**: Extensions can't discover it
- ❌ **Manual invocation**: Can't automatically trigger on context

#### IDE/Extension Compatibility

| Tool               | Works?     | How                     |
| ------------------ | ---------- | ----------------------- |
| VS Code            | ⚠️ Partial | Terminal only           |
| Cursor             | ⚠️ Partial | Terminal only           |
| Windsurf           | ⚠️ Partial | Terminal only           |
| Antigravity        | ✅ Yes     | Can call CLI commands   |
| GitHub Copilot     | ❌ No      | No integration          |
| Gemini Code Assist | ❌ No      | No integration          |
| Kilo Code          | ❌ No      | No integration          |
| Claude CLI         | ✅ Yes     | Can invoke via terminal |
| Gemini CLI         | ✅ Yes     | Can invoke via terminal |

**Verdict**: ⚠️ **Works for CLI, poor for IDE/extension integration**

---

### Method 2: MCP Server (Model Context Protocol)

#### How It Works

```bash
# Start MCP server (once, runs in background)
sdlc-mcp-server start --port 3000

# Now ANY MCP-compatible tool can use it:
# - Cursor (native MCP support)
# - Claude Desktop/CLI
# - VS Code extensions with MCP
# - Any tool supporting MCP protocol
```

#### Architecture

```
┌──────────────────────────────────────┐
│  SDLC Agent MCP Server               │
│  (Running on localhost:3000)         │
│                                      │
│  Exposes tools via MCP protocol:     │
│  - execute_phase()                   │
│  - review_checkpoint()               │
│  - generate_architecture()           │
│  - etc.                              │
└──────────────────────────────────────┘
        ↑ MCP Protocol
        │
┌───────┴────────┬──────────┬──────────┬─────────┐
│                │          │          │         │
VS Code     Cursor    Windsurf  Claude   Gemini
  ↓              ↓          ↓          ↓         ↓
Natural language: "Use sub agents to implement Phase 5"
```

#### MCP Configuration (Per IDE/Tool)

**Cursor** (`.cursor/mcp_servers.json`):

```json
{
  "mcpServers": {
    "sdlc-agent": {
      "command": "sdlc-mcp-server",
      "args": ["start"],
      "env": {}
    }
  }
}
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sdlc-agent": {
      "command": "sdlc-mcp-server",
      "args": ["start"]
    }
  }
}
```

**VS Code** (via MCP extension):

```json
{
  "mcp.servers": {
    "sdlc-agent": {
      "command": "sdlc-mcp-server"
    }
  }
}
```

#### Pros ✅

- ✅ **IDE-agnostic**: Works in ANY MCP-compatible IDE
- ✅ **Natural language**: "Use sub agents..." automatically routes
- ✅ **Extension-agnostic**: Any extension supporting MCP can use it
- ✅ **Automatic discovery**: IDEs detect available MCP servers
- ✅ **Context-aware**: MCP provides project context automatically
- ✅ **Universal protocol**: Industry standard (Claude, Cursor, many others)
- ✅ **Event-driven**: Can trigger on IDE events
- ✅ **Rich integration**: Full IDE integration, not just CLI

#### Cons ❌

- ❌ **Requires MCP support**: IDE/tool must support MCP protocol
- ❌ **Service dependency**: MCP server must be running
- ❌ **More complex setup**: Need to configure each IDE
- ❌ **Newer protocol**: Not all tools support it yet

#### IDE/Extension Compatibility (MCP)

| Tool                 | MCP Support       | Natural Language? |
| -------------------- | ----------------- | ----------------- |
| VS Code              | ✅ Via extensions | ✅ Yes            |
| Cursor               | ✅ Native         | ✅ Yes            |
| Windsurf             | ✅ Native         | ✅ Yes            |
| Antigravity (Gemini) | ✅ Yes            | ✅ Yes            |
| Claude Code          | ✅ Native         | ✅ Yes            |
| GitHub Copilot       | ⚠️ Planned        | ⚠️ Future         |
| Gemini Code Assist   | ✅ Yes (Google)   | ✅ Yes            |
| Kilo Code            | ✅ Yes            | ✅ Yes            |
| Roo Code             | ⚠️ Unknown        | ⚠️ Unknown        |
| Cline                | ✅ Yes            | ✅ Yes            |

**Verdict**: ✅ **EXCELLENT for IDE/extension integration, natural language**

---

### Method 3: Hybrid (pip + MCP) ⭐ **RECOMMENDED**

#### How It Works

```bash
# Installation creates BOTH:
pip install -e "path/to/sdlc-agent"

# This installs:
# 1. CLI command: 'sdlc'
# 2. MCP server: 'sdlc-mcp-server'

# Use via CLI:
sdlc execute --phase "Phase 5"

# OR use via MCP (in IDE):
# Natural language: "Use SDLC agents to implement data pipeline"
```

#### Architecture

```
┌─────────────────────────────────────────────┐
│  SDLC Agent Package                         │
│                                             │
│  ├── CLI Interface (sdlc command)           │
│  └── MCP Server (sdlc-mcp-server)           │
│      └── Both use same core agents          │
└─────────────────────────────────────────────┘
         ↓                    ↓
    CLI Usage          MCP Usage (IDEs)
```

#### Installation

```bash
# One command installs everything
pip install -e "/home/vincentspereira/Projects/AI Agents/Multi-Agent System/agents/agent - sdlc"

# Provides both:
sdlc --help                    # CLI
sdlc-mcp-server start          # MCP server
```

#### Usage Scenarios

**Scenario 1: Direct CLI Usage**

```bash
cd "/home/vincentspereira/Projects/Trading/RNR-IBKR-Algo-Trader"
sdlc init
sdlc execute --phase "Phase 5" --mode hybrid
```

**Scenario 2: Natural Language in Cursor**

```
You (in Cursor): "Use sub agents to implement Phase 5 data pipeline
with Kafka, achieving <100μs latency and >95% test coverage"

Cursor → Detects SDLC MCP server
      → Invokes execute_phase() tool
      → SDLC agents implement
      → Results returned to Cursor
      → You review in Cursor UI
```

**Scenario 3: Natural Language in Claude Code**

```bash
# In Claude Code CLI
$ "Please use the appropriate sub agents to build the fundamental
   analysis service with 50+ financial ratios"

Claude Code → Detects SDLC MCP server
            → Invokes SDLC agents
            → Implementation proceeds
            → You review and approve
```

**Scenario 4: Programmatic (in Python scripts)**

```python
from sdlc_agent import execute_phase

# Use programmatically
result = execute_phase(
    phase="Phase 5",
    mode="hybrid",
    project_root="/home/vincentspereira/Projects/Trading/RNR-IBKR-Algo-Trader"
)
```

#### Pros ✅

- ✅ **All benefits of pip**: CLI, Python API, standard workflow
- ✅ **All benefits of MCP**: IDE integration, natural language
- ✅ **Maximum flexibility**: Use whichever way suits the task
- ✅ **Single installation**: One command gets everything
- ✅ **No duplication**: Both interfaces use same core code

#### Cons ❌

- ❌ **Slightly more complex**: Two interfaces to understand
- ❌ **MCP setup needed**: Must configure IDEs for MCP (one-time)

**Verdict**: ⭐ **BEST OF BOTH WORLDS - HIGHLY RECOMMENDED**

---

### Method 4: VS Code Extension

#### How It Works

```bash
# Install as VS Code extension
# (Would need to publish to VS Code marketplace)

# Then in VS Code:
Extensions → Search "SDLC Agent" → Install
```

#### Pros ✅

- ✅ **Native VS Code integration**: Perfect for VS Code users
- ✅ **UI integration**: Buttons, panels, context menus
- ✅ **Marketplace**: Easy discovery and install

#### Cons ❌

- ❌ **VS Code only**: Doesn't work in Cursor, Windsurf, etc.
- ❌ **Requires separate extension**: One per IDE
- ❌ **Maintenance overhead**: Must maintain multiple extensions
- ❌ **Limited reach**: Only VS Code users benefit

**Verdict**: ❌ **Not recommended** (too IDE-specific, violates your requirement)

---

### Method 5: GitHub Copilot Extension

#### How It Works

```bash
# Create GitHub Copilot extension
# Users install via Copilot extensions

# Then in any IDE with Copilot:
@sdlc-agent execute phase 5
```

#### Pros ✅

- ✅ **Copilot integration**: Works where Copilot works
- ✅ **Natural interface**: @mentions

#### Cons ❌

- ❌ **Copilot-dependent**: Only works if user has Copilot
- ❌ **Paid service**: Requires GitHub Copilot subscription
- ❌ **Limited to Copilot IDEs**: Not truly IDE-agnostic

**Verdict**: ❌ **Not recommended** (too restrictive)

---

## Comparison Matrix

| Method                | Project-Agnostic | IDE-Agnostic | Natural Language | Auto-Updates | Setup Complexity  | Recommended |
| --------------------- | ---------------- | ------------ | ---------------- | ------------ | ----------------- | ----------- |
| **Pip Only**          | ✅               | ⚠️ Partial   | ❌               | ✅           | ⭐⭐⭐⭐⭐ Easy   | ⚠️          |
| **MCP Only**          | ✅               | ✅           | ✅               | ✅           | ⭐⭐⭐⭐ Moderate | ✅          |
| **Hybrid (pip+MCP)**  | ✅               | ✅           | ✅               | ✅           | ⭐⭐⭐⭐ Moderate | ⭐ **BEST** |
| **VS Code Extension** | ✅               | ❌           | ✅               | ⚠️           | ⭐⭐⭐ Moderate   | ❌          |
| **Copilot Extension** | ✅               | ⚠️           | ✅               | ⚠️           | ⭐⭐⭐ Moderate   | ❌          |

---

## Invocation Methods: Comprehensive Comparison

### Method 1: CLI Commands

#### Examples

```bash
# Direct command
sdlc execute --phase "Phase 5" --mode hybrid

# Interactive mode
sdlc interactive
> execute phase 5
> review architecture
> approve

# Scripted
sdlc batch --file phase_5_workflow.yaml
```

#### Pros ✅

- ✅ **Scriptable**: Can automate workflows
- ✅ **Precise control**: Exact parameters
- ✅ **CI/CD friendly**: Works in automation

#### Cons ❌

- ❌ **Manual typing**: Must remember commands
- ❌ **Not conversational**: No natural language
- ❌ **Context-switching**: Leave IDE to use terminal

---

### Method 2: Natural Language (via MCP)

#### Examples in Different IDEs

**In Cursor**:

```
You: "Use the SDLC sub agents to implement Phase 5 data pipeline"

Cursor AI:
- Detects SDLC MCP server
- Executes: execute_phase(phase="Phase 5", mode="hybrid")
- SDLC agents work
- Returns: "Phase 5 implementation ready for review"
```

**In Claude Code CLI**:

```bash
$ claude-code

You: "Please leverage the appropriate sub agents from the SDLC system
     to build the fundamental analysis service"

Claude:
- Detects SDLC MCP tools
- Invokes SDLC agents
- Presents results
```

**In Windsurf**:

```
You: "Use sub agents to optimize the trading engine for <100μs latency"

Windsurf:
- Calls SDLC MCP server
- Performance Optimizer agent engaged
- Code improvements implemented
```

#### Keyword Detection (How It Works)

The MCP server can be configured to respond to keywords:

```javascript
// MCP server keyword detection
const TRIGGER_KEYWORDS = [
  "sub agents",
  "sdlc agents",
  "use sub agents",
  "leverage sub agents",
  "appropriate sub agents",
  "sdlc system",
];

// When IDE sends prompt containing these keywords:
if (containsTriggerKeywords(userPrompt)) {
  // Route to SDLC agent system
  return executeSDLCAgent(userPrompt);
}
```

#### Pros ✅

- ✅ **Conversational**: Just describe what you want
- ✅ **No commands to remember**: Natural English
- ✅ **IDE-integrated**: Stay in your workflow
- ✅ **Context-aware**: IDE provides project context automatically

#### Cons ❌

- ❌ **Requires MCP**: IDE must support MCP
- ❌ **Ambiguity**: Natural language can be imprecise
- ❌ **Less control**: Harder to specify exact parameters

---

### Method 3: VS Code Commands (if using extension)

#### Examples

```
# Command Palette (Ctrl+Shift+P)
> SDLC: Execute Phase
> SDLC: Review Checkpoint
> SDLC: Approve Changes

# Context menu (right-click on file)
> SDLC Agent > Implement This Feature

# Code action (lightbulb)
> SDLC: Generate Tests for This Function
```

---

### Method 4: Programmatic API

#### Examples

```python
# In your own Python scripts
from sdlc_agent import SDLCOrchestrationHub

hub = SDLCOrchestrationHub()
result = hub.execute_phase(
    phase_name="Phase 5",
    mode="hybrid",
    project_path="C:/Users/.../RNR-IBKR-Algo-Trader"
)

# Check status
if result.status == "completed":
    print(f"Code generated: {result.files_created}")
```

---

## Update Mechanisms

### Challenge

```
Original source: /home/vincentspereira/Projects/AI Agents/Multi-Agent System/agents/agent - sdlc
Installed package: Python site-packages/sdlc_agent

Question: How to sync updates?
```

### Solution 1: Editable Install (Recommended for Development)

```bash
# Install in editable mode
pip install -e "/home/vincentspereira/Projects/AI Agents/Multi-Agent System/agents/agent - sdlc"

# This creates a LINK, not a copy:
# site-packages/sdlc-agent.egg-link → points to original directory

# Benefits:
# ✅ ANY changes you make in original directory immediately reflected
# ✅ No manual updates needed
# ✅ Perfect for active development
```

**How it works**:

```
Python site-packages/
└── sdlc-agent.egg-link  (just a pointer)
    ↓ Points to
C:\Users\...\Multi-Agent System\agents\agent - sdlc\
└── [actual code]  ← Edit here, changes immediately available
```

**Update process**: ✅ **AUTOMATIC** - just edit the source files!

---

### Solution 2: Version Tracking + Notification

```python
# In SDLC agent package: version.py
__version__ = "2.0.0"
__source_path__ = "C:/Users/.../agent - sdlc"

# Check for updates
def check_for_updates():
    # Read version from source
    source_version = read_version(SDLC_SOURCE_PATH)
    installed_version = __version__

    if source_version > installed_version:
        print(f"⚠️  SDLC Agent update available!")
        print(f"   Installed: {installed_version}")
        print(f"   Available: {source_version}")
        print(f"   Run: sdlc update")
        return True
    return False

# Auto-check on every invocation
if __name__ == "__main__":
    check_for_updates()
    # ... rest of CLI
```

**Usage**:

```bash
$ sdlc execute --phase "Phase 5"

⚠️  SDLC Agent update available!
   Installed: 2.0.0
   Available: 2.1.0
   Run: sdlc update

# User runs update
$ sdlc update
Updating SDLC Agent from 2.0.0 to 2.1.0...
Done! ✅
```

---

### Solution 3: Git-Based Updates

```python
# SDLC agent tracks its source via git
import subprocess

def update_sdlc_agent():
    source_path = "C:/Users/.../agent - sdlc"

    # Pull latest from git
    subprocess.run(["git", "pull"], cwd=source_path)

    # Reinstall
    subprocess.run(["pip", "install", "-e", source_path])

    print("✅ SDLC Agent updated!")
```

**Usage**:

```bash
$ sdlc update
Updating from git...
Pulling latest changes...
Reinstalling...
✅ SDLC Agent updated to latest version!
```

---

### Solution 4: Auto-Update on Startup (Optional)

```python
# Optional: Auto-update before every invocation
# (User can disable via config)

# .sdlc/config.yaml
auto_update: true  # or false

# In SDLC CLI
if config.auto_update and has_internet():
    update_sdlc_agent_silently()
```

---

## My Recommendation: The Complete Solution

### Architecture

```
┌──────────────────────────────────────────────┐
│  SDLC Agent Package (Source)                 │
│  Location: C:\Users\...\agent - sdlc         │
│                                              │
│  ├── setup.py (defines package)              │
│  ├── sdlc_agent/                             │
│  │   ├── cli/                                │
│  │   │   └── main.py (CLI entry point)       │
│  │   ├── mcp_server/                         │
│  │   │   └── server.py (MCP entry point)     │
│  │   ├── agents/ (21 sub-agents)             │
│  │   ├── orchestration/                      │
│  │   └── core/                               │
│  └── README.md                                │
└──────────────────────────────────────────────┘
         ↓ pip install -e .
┌──────────────────────────────────────────────┐
│  Installed (Editable Link)                   │
│  Location: Python site-packages              │
│                                              │
│  sdlc-agent.egg-link → points to source      │
│                                              │
│  Provides:                                   │
│  ├── sdlc (CLI command)                      │
│  └── sdlc-mcp-server (MCP server)            │
└──────────────────────────────────────────────┘
         ↓ Used by
┌──────────────────┬────────────┬──────────────┐
│  CLI Usage       │ MCP Usage  │ Python API   │
│                  │            │              │
│  $ sdlc execute  │ Cursor     │ import sdlc  │
│                  │ Windsurf   │              │
│                  │ Claude     │              │
│                  │ Gemini     │              │
└──────────────────┴────────────┴──────────────┘
```

### Installation Process

**Step 1: Package Structure** (I'll create)

```
C:\Users\...\agent - sdlc\
├── setup.py                  # Package configuration
├── pyproject.toml            # Modern Python package
├── README.md
├── sdlc_agent/
│   ├── __init__.py
│   ├── __version__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py          # CLI entry point
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   └── server.py        # MCP server entry point
│   ├── agents/              # Existing 21 sub-agents
│   ├── orchestration/       # Existing orchestration
│   └── core/                # Existing core logic
└── scripts/
    └── configure_mcp.py      # Helper to configure IDEs
```

**Step 2: Install**

```bash
# Editable install (changes immediately reflected)
pip install -e "/home/vincentspereira/Projects/AI Agents/Multi-Agent System/agents/agent - sdlc"

# This provides:
# - CLI: 'sdlc' command
# - MCP: 'sdlc-mcp-server' command
# - Python API: 'import sdlc_agent'
```

**Step 3: Configure MCP** (one-time per IDE)

```bash
# Helper script configures all IDEs automatically
sdlc configure-mcp --all

# Or manually for specific IDEs:
sdlc configure-mcp --ide cursor
sdlc configure-mcp --ide claude
sdlc configure-mcp --ide windsurf
```

**Step 4: Use Everywhere**

```bash
# CLI
$ sdlc execute --phase "Phase 5"

# Natural language in Cursor
"Use sub agents to implement this"

# Natural language in Claude
"Leverage SDLC agents for this feature"

# Python
from sdlc_agent import execute_phase
```

### Update Process

```bash
# You edit source files in:
# C:\Users\...\agent - sdlc\

# Changes immediately available (editable install)
# No manual update needed!

# Optional: Check version
$ sdlc --version
SDLC Agent v2.1.0
Source: C:\Users\...\agent - sdlc

# Optional: Force reinstall (rarely needed)
$ sdlc update
✅ Updated to latest version
```

---

## Summary: Recommended Approach

### Installation Method

**Hybrid (pip + MCP) with Editable Install** ⭐

### Why This Approach

1. ✅ **Project-Agnostic**: Works in any project directory
2. ✅ **IDE-Agnostic**: Works in VS Code, Cursor, Windsurf, Antigravity, etc.
3. ✅ **Extension-Agnostic**: Works with Gemini, Copilot, Kilo, Cline, etc.
4. ✅ **CLI-Agnostic**: Works in Claude CLI, Gemini CLI, terminal, etc.
5. ✅ **Natural Language**: "Use sub agents..." works everywhere
6. ✅ **Automatic Updates**: Editable install = instant updates
7. ✅ **Maximum Flexibility**: CLI, MCP, and Python API all available
8. ✅ **Single Source**: One codebase, multiple interfaces
9. ✅ **Easy Maintenance**: Edit source, changes everywhere

### Three Usage Modes

**Mode 1: CLI** (for scripts, automation)

```bash
sdlc execute --phase "Phase 5" --mode hybrid
```

**Mode 2: Natural Language** (in IDEs)

```
"Use the appropriate sub agents to implement the data pipeline"
```

**Mode 3: Programmatic** (in Python code)

```python
from sdlc_agent import execute_phase
result = execute_phase("Phase 5")
```

---

## Next Steps

Once you approve this architecture, I will:

1. ✅ Create `setup.py` and `pyproject.toml` for package definition
2. ✅ Create CLI interface (`sdlc_agent/cli/main.py`)
3. ✅ Create MCP server (`sdlc_agent/mcp_server/server.py`)
4. ✅ Create MCP configuration helper script
5. ✅ Create update notification system
6. ✅ Test installation and usage
7. ✅ Create configuration for RNR-IBKR-Algo-Trader project
8. ✅ Run pilot with Phase 5

**Ready to proceed with this architecture?**
