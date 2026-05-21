# FinceptTerminal — Adoption Assessment

**Repository:** https://github.com/Fincept-Corporation/FinceptTerminal
**Assessed:** 2026-05-21

## TL;DR — **Do not vendor any FinceptTerminal code**

Three independent reasons. Any one of them is sufficient to walk away.

1. **License is a hostile dual-license**, not a permissive AGPL. Commercial fee is USD 10,200/year, liquidated damages USD 50K–250K, India-jurisdiction. The phrase *"cloning/forking doesn't grant commercial rights"* explicitly defeats the "merge into MAS" plan.
2. **Architecture mismatch.** FinceptTerminal v4 is a **C++20 / Qt6 native desktop application** with Python embedded as a sub-runtime. IBKR Algo Trader is a Python microservices system with a Next.js web front-end. There is no clean "module" you can import.
3. **Feature overlap is total, not complementary.** It already does what your repo aims to do — its own broker integrations (including IBKR), its own AI-agent framework, its own QuantLib bindings, its own backtester. Merging means duplicating two competing systems, not enriching one.

## License Confirmation (from upstream `LICENSE`)

> **GNU AFFERO GENERAL PUBLIC LICENSE — Version 3, 19 November 2007**
>
> Dual-licensing model:
> - **Free under AGPL-3.0** for non-commercial use (personal learning, academic research, open-source contribution)
> - **Commercial use requires a paid Commercial License** (USD 10,200/year)
> - Commercial use is defined broadly: *any business purpose, internal corporate use, startups, fintech entities, hosted offerings*
> - *"Cloning/forking doesn't grant commercial rights — the licensing obligation attaches to the codebase itself"*
> - *"Substituting APIs does not eliminate obligations"*
> - Trademark + trade dress protections prevent rebranding
> - Liquidated damages USD 50,000–250,000+
> - Governing law: Republic of India (Delhi courts, exclusive jurisdiction)
> - Applies retroactively to all versions

The retroactive + anti-substitution clauses are unusually aggressive. Even reimplementing an "API equivalent" carries claimed obligations. We respect that and stay clear.

## What FinceptTerminal Actually Is

| Aspect | Detail |
|--------|--------|
| Stack | C++20 + Qt6 + embedded Python 3.11.9 |
| Distribution | Native binaries (Windows/Linux/macOS), Docker, manual CMake build |
| UI paradigm | Desktop terminal-style GUI, similar to Bloomberg Terminal |
| Brokers | 16 integrations (Zerodha, Angel One, Upstox, Fyers, Dhan, Groww, Kotak, IIFL, 5paisa, AliceBlue, Shoonya, Motilal, IBKR, Alpaca, Tradier, Saxo) plus Kraken / HyperLiquid for crypto |
| Data sources | "100+ connectors" — DBnomics, Polygon, Kraken, Yahoo Finance, FRED, IMF, World Bank, government APIs |
| Analytics | DCF, portfolio optimization, VaR, Sharpe, derivatives (QuantLib 18 modules), maritime/geopolitical intel |
| AI agents | 37 agents, local LLM + multi-provider (OpenAI, Anthropic) |
| Workflow | Node-based workflow automation, paper trading engine |

It is essentially a competing all-in-one trading terminal, not a library.

## What You Could Legitimately Borrow

Two kinds of value transfer are licence-safe:

### 1. Concept inspiration (always safe)

Ideas are not copyrightable. You can look at FinceptTerminal's feature catalogue and decide *what* you want, then implement your own version without consulting their source. Concepts worth stealing:

- **Data source breadth.** The list of upstream macro data providers — DBnomics, FRED, IMF, World Bank — is genuinely useful and you don't have all of these yet. Build your own thin REST clients; none of these providers are owned by Fincept.
- **Node-based workflow editor concept.** If you ever build a strategy designer, a node-based UI is well-trodden territory (Unreal Blueprint, n8n, Langflow). Do not copy their implementation.
- **"AI agents per task" framing.** You already have LangGraph multi-agent — Fincept's 37-agent inventory is just a longer menu. Pick agent roles that map to your domain.

### 2. Public-API integrations (always safe)

Broker APIs and data APIs are not owned by Fincept. If you want to add a broker integration that they happen to also support, you write the integration against the broker's documentation directly. The fact that Fincept also integrates that broker is irrelevant.

For your IBKR-centric system, the only additions of plausible interest are:

- **Alpaca** — already has a stub in `core_trading/adapters/brokers/alpaca.py` (gutted). If you want commission-free US equities backup, implement against Alpaca's public docs.
- **Saxo** — broader instrument universe than IBKR; relevant only if you trade exotic derivatives.
- **Tradier** — cheap options data API; relevant if you want options data without IBKR market data subs.

The India-focused brokers (Zerodha, Angel One, Upstox, Fyers, Dhan, Groww, etc.) are only useful if you trade Indian markets.

## Module-by-Module Verdict

Since the project has no Python module structure to clone, the verdict for every "module" is the same:

| FinceptTerminal Feature | Recommendation |
|------------------------|---------------|
| C++20 / Qt6 native UI | **SKIP** — you have a Next.js web UI; rewriting is huge |
| 16 broker integrations | **CLEAN-ROOM (selective)** — only for brokers you actually need; write from broker docs not Fincept source |
| 100+ data connectors | **CLEAN-ROOM (selective)** — only DBnomics / FRED / IMF / World Bank are worth adding; write from upstream API docs |
| QuantLib 18 modules | **ALREADY HAVE** — you have `quantlib>=1.32` in `requirements.txt` |
| 37 AI agents | **SKIP** — overlaps with your LangGraph multi-agent; expanding your own roster is faster than borrowing |
| Node-based workflow | **DEFER** — interesting feature; build only if customer demand justifies it |
| Maritime/geopolitical intel | **SKIP** — niche; not relevant to retail algo trading |
| Paper trading engine | **ALREADY HAVE** — your IBKR adapter targets paper trading directly |

## Recommendation

**Do not adopt FinceptTerminal in any form.** The license-vs-commercialisation conflict is fatal; the architecture is incompatible; the features overlap rather than complement.

**Instead, treat it as competitive intelligence.** Read their feature list, identify gaps in your own roadmap, and prioritise:

1. **FRED / IMF / World Bank macro data connectors** — implement against the public APIs directly. ~1-2 days work per source, fully MAS-safe under MIT/BSD.
2. **An Alpaca integration** — your `alpaca.py` is a gutted stub. Rewrite against the Alpaca SDK (Apache-2.0 licensed, MAS-safe).
3. **A Tradier integration for options data** — only if your options pipeline outgrows IBKR's data subs.

That's it. Everything else FinceptTerminal offers you either already have, or can build directly from public sources at lower legal risk.

## What I Would Do With FinceptTerminal Personally

If you want to *use* FinceptTerminal as an end-user on your laptop (no merging, no MAS integration, no commercial deployment), you can install it under AGPL-3.0 for free. It's a Bloomberg-style terminal — fine as a research tool. Just keep it **physically separate** from this project's tree and from MAS — never let its code or any derivative reach those repositories.
