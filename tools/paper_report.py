"""Static HTML report over all paper-trading books.

Renders one self-contained HTML page (equity curves, drawdowns, promotion
progress, positions, recent orders/fills, incidents) from the ledgers under
``logs/``. Regenerated automatically at the end of every live
``tools/taquant_paper_run.py`` invocation; can be run standalone any time.

The page embeds its data as inline JSON and draws charts with Chart.js from
a CDN; without internet the tables and numbers still render (charts show a
fallback note).

Run:
    .venv/bin/python tools/paper_report.py
    .venv/bin/python tools/paper_report.py --output logs/paper_report.html
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUTPUT = REPO_ROOT / "logs" / "paper_report.html"

_CHARTJS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Paper Trading Report</title>
<script src="__CHARTJS__"></script>
<style>
  :root { color-scheme: dark; }
  body { font-family: Segoe UI, system-ui, sans-serif; background:#14171c; color:#dde3ea; margin:0; padding:24px; }
  h1 { font-size:20px; margin:0 0 4px; }
  .sub { color:#8b97a5; font-size:12px; margin-bottom:20px; }
  .banner { padding:10px 14px; border-radius:8px; margin-bottom:16px; font-weight:600; }
  .banner.ok { background:#10331f; color:#7fd6a2; }
  .banner.bad { background:#3a1518; color:#f08f96; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(420px, 1fr)); gap:16px; }
  .card { background:#1c2128; border:1px solid #2a313a; border-radius:10px; padding:16px; }
  .card h2 { font-size:15px; margin:0 0 2px; }
  .lane { color:#8b97a5; font-size:11px; text-transform:uppercase; letter-spacing:.06em; }
  .kpis { display:flex; flex-wrap:wrap; gap:14px; margin:10px 0; }
  .kpi { min-width:90px; }
  .kpi .v { font-size:16px; font-weight:600; }
  .kpi .l { font-size:10px; color:#8b97a5; text-transform:uppercase; letter-spacing:.05em; }
  .pos { color:#7fd6a2; } .neg { color:#f08f96; }
  .chartbox { height:180px; position:relative; }
  table { width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }
  th, td { text-align:left; padding:3px 6px; border-bottom:1px solid #262d36; }
  th { color:#8b97a5; font-weight:500; }
  .progress { background:#262d36; border-radius:6px; height:8px; overflow:hidden; margin-top:6px; }
  .progress > div { background:#4f8ef7; height:100%; }
  .halted { color:#f08f96; font-weight:700; }
  .small { font-size:11px; color:#8b97a5; }
  details summary { cursor:pointer; color:#8b97a5; font-size:12px; margin-top:8px; }
</style>
</head>
<body>
<h1>Paper Trading Report</h1>
<div class="sub" id="generated"></div>
<div id="banner"></div>
<div class="grid" id="cards"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const S = JSON.parse(document.getElementById('data').textContent);
document.getElementById('generated').textContent =
  `generated ${S.generated_utc} | ${S.n_books} book(s) | total marked equity ${S.total_marked_equity.toLocaleString()}`;
const banner = document.getElementById('banner');
if (S.any_halted || S.open_incidents > 0) {
  banner.innerHTML = `<div class="banner bad">ATTENTION: ${S.open_incidents} open incident(s); halted books present. Review --status and --reset-halt.</div>`;
} else {
  banner.innerHTML = `<div class="banner ok">All books healthy. No open incidents, no kill switches engaged.</div>`;
}
const fmtPct = x => (x >= 0 ? '+' : '') + (100 * x).toFixed(2) + '%';
const cls = x => (x >= 0 ? 'pos' : 'neg');
const cards = document.getElementById('cards');
for (const [i, b] of S.books.entries()) {
  const promo = b.promotion || {};
  const nDays = promo.n_days || 0;
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `
    <div class="lane">${b.lane}</div>
    <h2>${b.name} ${b.halted ? '<span class="halted">[HALTED]</span>' : ''}</h2>
    <div class="small">started ${b.started || '(not started)'} | last run ${b.last_run_date || '-'} | last status ${b.last_status || '-'}</div>
    <div class="kpis">
      <div class="kpi"><div class="v">${(b.equity_values.at(-1) ?? 0).toLocaleString()}</div><div class="l">equity</div></div>
      <div class="kpi"><div class="v ${cls(b.total_return)}">${fmtPct(b.total_return)}</div><div class="l">total return</div></div>
      <div class="kpi"><div class="v ${cls(b.max_drawdown)}">${fmtPct(b.max_drawdown)}</div><div class="l">max drawdown</div></div>
      <div class="kpi"><div class="v">${b.paper_sharpe.toFixed(2)}</div><div class="l">paper sharpe</div></div>
      <div class="kpi"><div class="v">${Number(b.gross_leverage).toFixed(2)}</div><div class="l">gross</div></div>
      <div class="kpi"><div class="v">${b.n_positions}</div><div class="l">positions</div></div>
    </div>
    <div class="chartbox"><canvas id="chart${i}"></canvas></div>
    <div class="small" style="margin-top:8px">promotion: ${nDays}/90 active days</div>
    <div class="progress"><div style="width:${Math.min(100, nDays / 90 * 100)}%"></div></div>
    ${b.open_incidents.length ? `<div class="small halted" style="margin-top:8px">incidents:<br>${b.open_incidents.join('<br>')}</div>` : ''}
    <details><summary>positions, orders &amp; fills</summary>
      <table><tr><th>symbol</th><th>shares</th></tr>
        ${Object.entries(b.positions).map(([s, q]) => `<tr><td>${s}</td><td>${q}</td></tr>`).join('') || '<tr><td colspan="2">flat</td></tr>'}
      </table>
      <table><tr><th>date</th><th>side</th><th>qty</th><th>symbol</th></tr>
        ${b.recent_orders.slice(0, 12).map(o => `<tr><td>${o.date}</td><td>${o.side}</td><td>${o.quantity}</td><td>${o.symbol}</td></tr>`).join('') || '<tr><td colspan="4">no orders yet</td></tr>'}
      </table>
      <table><tr><th>date</th><th>side</th><th>qty</th><th>symbol</th><th>avg px</th></tr>
        ${b.recent_fills.slice(-12).reverse().map(f => `<tr><td>${f.date}</td><td>${f.side}</td><td>${f.quantity}</td><td>${f.symbol}</td><td>${f.avg_price ?? ''}</td></tr>`).join('') || '<tr><td colspan="5">no fills yet</td></tr>'}
      </table>
    </details>`;
  cards.appendChild(card);
}
if (typeof Chart === 'undefined') {
  document.querySelectorAll('.chartbox').forEach(el => {
    el.innerHTML = '<div class="small">charts need internet (Chart.js CDN); data tables above are complete</div>';
  });
} else {
  for (const [i, b] of S.books.entries()) {
    new Chart(document.getElementById('chart' + i), {
      type: 'line',
      data: { labels: b.equity_dates, datasets: [{ data: b.equity_values, borderColor: '#4f8ef7', borderWidth: 1.6, pointRadius: 0, fill: false }] },
      options: { animation: false, plugins: { legend: { display: false } },
        scales: { x: { ticks: { maxTicksLimit: 6, color: '#8b97a5' }, grid: { color: '#232a33' } },
                  y: { ticks: { color: '#8b97a5' }, grid: { color: '#232a33' } } },
        maintainAspectRatio: false }
    });
  }
}
</script>
</body>
</html>
"""


def build_report_html(summary: dict) -> str:
    """Render the report page from a ``summarise_books`` payload."""
    data = json.dumps(summary).replace("</", "<\\/")  # avoid </script> breakout
    return _PAGE.replace("__CHARTJS__", _CHARTJS_CDN).replace("__DATA__", data)


def generate_report(
    logs_root: Path | None = None, output: Path | None = None
) -> Path:
    """Build and write the report; returns the output path."""
    from core_trading.ops.paper_telemetry import summarise_books

    root = logs_root if logs_root is not None else REPO_ROOT / "logs"
    out = output if output is not None else DEFAULT_OUTPUT
    summary = summarise_books(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report_html(summary), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--logs-root", default=None, help="override logs directory")
    parser.add_argument("--output", default=None, help=f"output path (default {DEFAULT_OUTPUT})")
    args = parser.parse_args(argv)
    out = generate_report(
        Path(args.logs_root) if args.logs_root else None,
        Path(args.output) if args.output else None,
    )
    print(f"report written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
