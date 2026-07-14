"""Daily operations report runner (Phase 7/9 DOD operator wiring).

Designed to be invoked nightly by cron (22:30 local,
with catch-up if the machine was off). Produces, under
``logs/reports/YYYY-MM-DD/``:

1. ``risk_report.md``  -- the Phase 7 daily risk report.
2. ``tca_report.md``   -- the Phase 9.4 daily transaction-cost report.
3. ``reconciliation.md`` -- the Phase 9.6 internal-vs-broker fills check.
4. ``status.txt``      -- one-line outcome per report + reminders.

Data sources are auto-detected and each report degrades gracefully:

* Until live paper trading is running and the trading-engine Postgres
  store is reachable, the risk and TCA reports run in ``--demo`` pipe-check
  mode (proves the report machinery end-to-end) and reconciliation reports
  ``NO FILLS SOURCE`` instead of failing.
* Once real fills exist, the same script picks them up without changes.

Impact-recalibration reminder (Phase 9 DOD item 3): the script tracks the
date of the first observed real fill in ``logs/reports/first_fill.txt``.
Once 30+ days have elapsed it writes ``RECALIBRATION_DUE.txt`` at the repo
root and flags it in ``status.txt`` -- the cue to ask Claude to
"recalibrate the impact models on the real fills".

Run manually:
    .venv/bin/python tools/daily_ops.py
"""
from __future__ import annotations

import datetime as _dt
import io
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

REPORTS_ROOT = REPO_ROOT / "logs" / "reports"
RECAL_DAYS = 30


def _today_dir() -> Path:
    day = _dt.date.today().isoformat()
    out = REPORTS_ROOT / day
    out.mkdir(parents=True, exist_ok=True)
    return out


def _run_risk_report(out_dir: Path) -> str:
    """Phase 7 daily risk report (demo mode until a live portfolio feed exists)."""
    try:
        from core_trading.risk.daily_report import main as risk_main
        target = out_dir / "risk_report.md"
        risk_main(["--demo", "--output", str(target)])
        return "OK risk_report.md (demo mode -- live portfolio feed not wired yet)"
    except SystemExit as exc:  # CLI mains may sys.exit(0)
        if getattr(exc, "code", 0) in (0, None):
            return "OK risk_report.md (demo mode -- live portfolio feed not wired yet)"
        return f"ERR risk report exited with code {exc.code}"
    except Exception:
        return "ERR risk report:\n" + traceback.format_exc()


def _run_tca_report(out_dir: Path) -> str:
    """Phase 9.4 daily TCA report (demo mode until real fills exist)."""
    try:
        from core_trading.execution.tca import main as tca_main
        target = out_dir / "tca_report.md"
        tca_main(["--demo", "--output", str(target)])
        return "OK tca_report.md (demo mode -- no real fills yet)"
    except SystemExit as exc:
        if getattr(exc, "code", 0) in (0, None):
            return "OK tca_report.md (demo mode -- no real fills yet)"
        return f"ERR tca report exited with code {exc.code}"
    except Exception:
        return "ERR tca report:\n" + traceback.format_exc()


def _fetch_fills_from_store() -> object | None:
    """Load today's fills in the lifecycle reconciliation column contract.

    Sources, in order:

    1. The pairs live-runner fill stream (``logs/pairs_paper/fills.jsonl``,
       written by ``tools/pairs_paper_run.py``) -- the operational source
       once the Phase 4.10 paper pilot is running.
    2. The trading-engine Postgres store -- still deliberately not wired
       (the engine does not run nightly yet).

    Returns a DataFrame with columns ``order_id, qty, price, fees`` or
    ``None`` when no fills exist for today.
    """
    import json

    fills_path = REPO_ROOT / "logs" / "pairs_paper" / "fills.jsonl"
    if fills_path.exists():
        today = _dt.date.today().isoformat()
        rows = []
        for line in fills_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("date") == today:
                rows.append(
                    {
                        "order_id": str(rec.get("order_id")),
                        "qty": float(rec.get("quantity", 0.0)),
                        "price": float(rec.get("avg_price", 0.0)),
                        # The runner does not capture commissions yet; fees
                        # arrive with the broker drop-copy side.
                        "fees": 0.0,
                    }
                )
        if rows:
            import pandas as pd

            return pd.DataFrame(rows)
    return None


def _run_reconciliation(out_dir: Path) -> str:
    """Phase 9.6 daily reconciliation (no-op until a fills source exists)."""
    target = out_dir / "reconciliation.md"
    fills = _fetch_fills_from_store()
    if fills is not None and len(fills) > 0:
        # First real fills observed: start the recalibration countdown.
        marker = REPORTS_ROOT / "first_fill.txt"
        if not marker.exists():
            marker.write_text(_dt.date.today().isoformat() + "\n", encoding="utf-8")
    if fills is None:
        target.write_text(
            "# Daily reconciliation\n\n"
            "NO FILLS SOURCE: trading-engine order store not reachable or empty.\n"
            "This is expected until live paper trading is running.\n",
            encoding="utf-8",
        )
        return "SKIP reconciliation.md (no fills source yet -- expected pre-paper-trading)"
    try:
        from core_trading.execution.lifecycle import (
            render_reconciliation,
            run_daily_reconciliation,
        )
        # Until an independent broker drop-copy feed is wired, the runner's
        # own fills serve as both sides: a pipe check that exercises the
        # full reconciliation path and starts the recalibration countdown.
        report = run_daily_reconciliation(fills, fills)
        body = render_reconciliation(report) + (
            "\nNOTE: broker drop-copy side not wired yet; this run "
            "self-reconciles the pairs runner's fill stream (pipe check).\n"
        )
        target.write_text(body, encoding="utf-8")
        verdict = "CLEAN" if report.clean else "MISMATCHES FOUND"
        return f"OK reconciliation.md ({verdict}; self-reconciliation pipe check)"
    except Exception:
        return "ERR reconciliation:\n" + traceback.format_exc()


def _recalibration_reminder() -> str:
    """Track first real fill; flag impact recalibration after RECAL_DAYS days."""
    marker = REPORTS_ROOT / "first_fill.txt"
    due_flag = REPO_ROOT / "RECALIBRATION_DUE.txt"
    if not marker.exists():
        # No real fills observed yet; nothing to count down from.
        return "recalibration: waiting for first real fill (no countdown started)"
    try:
        first = _dt.date.fromisoformat(marker.read_text(encoding="utf-8").strip())
    except ValueError:
        return "recalibration: first_fill.txt unreadable; fix or delete it"
    elapsed = (_dt.date.today() - first).days
    if elapsed >= RECAL_DAYS:
        due_flag.write_text(
            f"Impact-model recalibration is DUE ({elapsed} days of fills since {first}).\n"
            "Open a Claude session and say: 'recalibrate the impact models on the real fills'.\n",
            encoding="utf-8",
        )
        return f"recalibration: DUE ({elapsed} days of fills) -- RECALIBRATION_DUE.txt written"
    return f"recalibration: {elapsed}/{RECAL_DAYS} days of fills elapsed"


def main() -> int:
    out_dir = _today_dir()
    lines = [f"daily_ops run {_dt.datetime.now().isoformat(timespec='seconds')}"]
    buf = io.StringIO()
    with redirect_stdout(buf):  # keep CLI mains' stdout out of scheduler logs
        lines.append(_run_risk_report(out_dir))
        lines.append(_run_tca_report(out_dir))
        lines.append(_run_reconciliation(out_dir))
    lines.append(_recalibration_reminder())
    status = "\n".join(lines) + "\n"
    (out_dir / "status.txt").write_text(status, encoding="utf-8")
    print(status)
    return 1 if "ERR" in status else 0


if __name__ == "__main__":
    raise SystemExit(main())
