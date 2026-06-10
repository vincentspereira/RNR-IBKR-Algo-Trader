"""Live operator dashboard -- local web UI over all paper-trading books.

A small FastAPI app that re-reads the ledgers under ``logs/`` on every
request and serves a dark single-page UI that auto-refreshes every 5
seconds. It shows, per book: equity curve, total return, drawdown, paper
Sharpe, gross leverage, open positions, today's orders and fills,
kill-switch state, incidents, and 90-day promotion progress. The intraday
experimental lane (``logs/intraday_paper/``) appears automatically the
moment it writes its first ledger record, as does any future slot.

Read-only by design: the dashboard never talks to TWS and never mutates
state, so it cannot interfere with the runners or burn a TWS client id.
Bind is localhost-only.

Run:
    .venv/Scripts/python.exe tools/dashboard_server.py            # http://127.0.0.1:8642
    .venv/Scripts/python.exe tools/dashboard_server.py --port 9000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

from core_trading.ops.paper_telemetry import summarise_books  # noqa: E402

LOGS_ROOT = REPO_ROOT / "logs"

app = FastAPI(title="IBKR Algo Trader -- Operator Dashboard", docs_url=None, redoc_url=None)

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Operator Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
  :root { color-scheme: dark; }
  body { font-family: Segoe UI, system-ui, sans-serif; background:#14171c; color:#dde3ea; margin:0; padding:20px; }
  header { display:flex; align-items:baseline; gap:14px; margin-bottom:14px; }
  h1 { font-size:18px; margin:0; }
  #meta { color:#8b97a5; font-size:12px; }
  #pulse { width:8px; height:8px; border-radius:50%; background:#7fd6a2; display:inline-block; }
  .banner { padding:8px 12px; border-radius:8px; margin-bottom:14px; font-weight:600; font-size:13px; }
  .banner.ok { background:#10331f; color:#7fd6a2; } .banner.bad { background:#3a1518; color:#f08f96; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(420px, 1fr)); gap:14px; }
  .card { background:#1c2128; border:1px solid #2a313a; border-radius:10px; padding:14px; }
  .lane { color:#8b97a5; font-size:10px; text-transform:uppercase; letter-spacing:.06em; }
  .card h2 { font-size:14px; margin:2px 0 2px; }
  .small { font-size:11px; color:#8b97a5; }
  .kpis { display:flex; flex-wrap:wrap; gap:12px; margin:8px 0; }
  .kpi .v { font-size:15px; font-weight:600; } .kpi .l { font-size:9px; color:#8b97a5; text-transform:uppercase; }
  .pos { color:#7fd6a2; } .neg { color:#f08f96; } .halted { color:#f08f96; font-weight:700; }
  .chartbox { height:150px; position:relative; }
  table { width:100%; border-collapse:collapse; font-size:11px; margin-top:6px; }
  th, td { text-align:left; padding:2px 5px; border-bottom:1px solid #262d36; }
  th { color:#8b97a5; font-weight:500; }
  .progress { background:#262d36; border-radius:6px; height:6px; overflow:hidden; margin-top:4px; }
  .progress > div { background:#4f8ef7; height:100%; }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
</style>
</head>
<body>
<header><h1>Operator Dashboard</h1><span id="pulse"></span><span id="meta">connecting...</span></header>
<div id="banner"></div>
<div class="grid" id="cards"></div>
<script>
const charts = {};
const fmtPct = x => (x >= 0 ? '+' : '') + (100 * x).toFixed(2) + '%';
const cls = x => (x >= 0 ? 'pos' : 'neg');

function renderCard(b, i) {
  const promo = b.promotion || {};
  const nDays = promo.n_days || 0;
  return `
    <div class="lane">${b.lane}</div>
    <h2>${b.name} ${b.halted ? '<span class="halted">[HALTED: ' + (b.halt_reason || '') + ']</span>' : ''}</h2>
    <div class="small">started ${b.started || '(not started)'} | last run ${b.last_run_date || '-'} | status ${b.last_status || '-'} ${b.last_reason ? '(' + b.last_reason + ')' : ''}</div>
    <div class="kpis">
      <div class="kpi"><div class="v">${(b.equity_values.at(-1) ?? 0).toLocaleString()}</div><div class="l">equity</div></div>
      <div class="kpi"><div class="v">${Number(b.cash).toLocaleString()}</div><div class="l">cash</div></div>
      <div class="kpi"><div class="v ${cls(b.total_return)}">${fmtPct(b.total_return)}</div><div class="l">total ret</div></div>
      <div class="kpi"><div class="v ${cls(b.max_drawdown)}">${fmtPct(b.max_drawdown)}</div><div class="l">max dd</div></div>
      <div class="kpi"><div class="v">${b.paper_sharpe.toFixed(2)}</div><div class="l">sharpe</div></div>
      <div class="kpi"><div class="v">${Number(b.gross_leverage).toFixed(2)}</div><div class="l">gross</div></div>
      <div class="kpi"><div class="v">${b.n_traded}</div><div class="l">traded days</div></div>
    </div>
    <div class="chartbox"><canvas id="chart${i}"></canvas></div>
    <div class="small" style="margin-top:6px">promotion ${nDays}/90 active days</div>
    <div class="progress"><div style="width:${Math.min(100, nDays / 90 * 100)}%"></div></div>
    ${b.open_incidents.length ? `<div class="small halted" style="margin-top:6px">${b.open_incidents.join('<br>')}</div>` : ''}
    <div class="cols">
      <table><tr><th>position</th><th>shares</th></tr>
        ${Object.entries(b.positions).slice(0, 14).map(([s, q]) => `<tr><td>${s}</td><td>${q}</td></tr>`).join('') || '<tr><td colspan="2">flat</td></tr>'}
      </table>
      <table><tr><th>last fills</th><th>side</th><th>qty</th><th>px</th></tr>
        ${b.recent_fills.slice(-8).reverse().map(f => `<tr><td>${f.symbol}</td><td>${f.side}</td><td>${f.quantity}</td><td>${f.avg_price ?? ''}</td></tr>`).join('') || '<tr><td colspan="4">none</td></tr>'}
      </table>
    </div>`;
}

async function refresh() {
  let s;
  try {
    s = await (await fetch('/api/summary')).json();
    document.getElementById('pulse').style.background = '#7fd6a2';
  } catch (e) {
    document.getElementById('pulse').style.background = '#f08f96';
    return;
  }
  document.getElementById('meta').textContent =
    `${s.generated_utc} | ${s.n_books} book(s) | total marked equity ${s.total_marked_equity.toLocaleString()} | refresh 5s`;
  document.getElementById('banner').innerHTML = (s.any_halted || s.open_incidents > 0)
    ? `<div class="banner bad">ATTENTION: ${s.open_incidents} open incident(s) / halted book present</div>`
    : `<div class="banner ok">All books healthy</div>`;
  const cards = document.getElementById('cards');
  if (cards.children.length !== s.books.length) {
    cards.innerHTML = '';
    for (const [i, b] of s.books.entries()) {
      const d = document.createElement('div');
      d.className = 'card';
      d.id = 'card' + i;
      cards.appendChild(d);
    }
    for (const k of Object.keys(charts)) { charts[k].destroy(); delete charts[k]; }
  }
  for (const [i, b] of s.books.entries()) {
    document.getElementById('card' + i).innerHTML = renderCard(b, i);
    if (typeof Chart !== 'undefined') {
      if (charts[i]) charts[i].destroy();
      charts[i] = new Chart(document.getElementById('chart' + i), {
        type: 'line',
        data: { labels: b.equity_dates, datasets: [{ data: b.equity_values, borderColor: '#4f8ef7', borderWidth: 1.5, pointRadius: 0, fill: false }] },
        options: { animation: false, plugins: { legend: { display: false } },
          scales: { x: { ticks: { maxTicksLimit: 6, color: '#8b97a5' }, grid: { color: '#232a33' } },
                    y: { ticks: { color: '#8b97a5' }, grid: { color: '#232a33' } } },
          maintainAspectRatio: false }
      });
    }
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE


@app.get("/api/summary")
def api_summary() -> JSONResponse:
    return JSONResponse(summarise_books(LOGS_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8642)
    args = parser.parse_args(argv)

    import uvicorn

    print(f"Operator dashboard: http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
