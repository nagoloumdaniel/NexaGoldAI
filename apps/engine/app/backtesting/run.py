"""Backtest de la stratégie liquidity_sweep sur l'historique M1 stocké en base.

Usage :
  .venv\\Scripts\\python.exe -m app.backtesting.run --days 90
  .venv\\Scripts\\python.exe -m app.backtesting.run --days 90 --spread-pct 0.0002 --slippage-pct 0.0001

Écrit reports/backtests/<run_id>/ (summary.json, trades.csv, equity_curve.csv)
à la racine du dépôt et affiche un résumé. Lecture seule sur la base ; aucun
ordre, aucun broker.
"""

import argparse
import asyncio
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.backtesting.engine import CostModel, EventBacktester
from app.config import Settings, get_settings
from app.db import Database
from app.strategy_v2.state_machine import SetupStateMachine
from app.strategy_v2.sweep_strategy import LiquiditySweepStrategy, SweepConfig

REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports" / "backtests"


async def load_m1(days: int) -> list[dict]:
    settings = get_settings()
    db = Database(settings)
    await db.connect()
    if not db.is_connected:
        raise SystemExit("Base de données indisponible (DATABASE_URL)")
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    try:
        rows = await db.pool.fetch(
            'SELECT "time", "open", "high", "low", "close", "volume" '
            'FROM "Candle" WHERE "instrument" = $1 AND "granularity" = \'M1\' '
            'AND "time" >= $2 ORDER BY "time"',
            settings.symbol,
            cutoff,
        )
    finally:
        await db.close()
    return [
        {
            "time": r["time"].strftime("%Y-%m-%dT%H:%M:%S"),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["volume"]),
        }
        for r in rows
    ]


def build_strategy(args: argparse.Namespace) -> LiquiditySweepStrategy:
    strategy_settings = Settings(
        _env_file=None,
        sessions_enabled=not args.no_sessions,
        allowed_sessions=args.sessions,
        avoid_session_edges_minutes=5,
        sweep_require_retest=not args.no_retest,
        sweep_min_risk_reward=args.risk_reward,
    )
    config = SweepConfig(
        require_retest=not args.no_retest, risk_reward=args.risk_reward
    )
    # FSM sans persistance : le backtest ne doit pas polluer l'état live.
    return LiquiditySweepStrategy(strategy_settings, config, SetupStateMachine())


def write_report(report: dict, run_id: str) -> Path:
    out_dir = REPORTS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    trade_list = report.pop("trade_list")
    equity_curve = report.pop("equity_curve")
    (out_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if trade_list:
        with (out_dir / "trades.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(trade_list[0].keys()))
            writer.writeheader()
            writer.writerows(trade_list)
    with (out_dir / "equity_curve.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "equity"])
        writer.writerows(equity_curve)
    return out_dir


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest liquidity_sweep sur M1")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--spread-pct", type=float, default=0.00012)
    parser.add_argument("--slippage-pct", type=float, default=0.00003)
    parser.add_argument("--commission-pct", type=float, default=0.0)
    parser.add_argument("--risk-reward", type=float, default=2.0)
    parser.add_argument("--risk-pct", type=float, default=0.5)
    parser.add_argument("--window", type=int, default=240)
    parser.add_argument("--sessions", default="LONDON,NEW_YORK")
    parser.add_argument("--no-sessions", action="store_true")
    parser.add_argument("--no-retest", action="store_true")
    args = parser.parse_args()

    m1 = await load_m1(args.days)
    if len(m1) < 2000:
        raise SystemExit(
            f"Seulement {len(m1)} bougies M1 en base — lancer d'abord "
            "python -m app.data.backfill_cli --granularity M1 --days N"
        )
    print(f"{len(m1)} bougies M1 ({m1[0]['time']} -> {m1[-1]['time']})")

    strategy = build_strategy(args)
    engine = EventBacktester(
        strategy,
        CostModel(args.spread_pct, args.slippage_pct, args.commission_pct),
        window_bars=args.window,
        risk_pct_per_trade=args.risk_pct,
    )
    started = datetime.now()
    report = engine.run(m1)
    elapsed = (datetime.now() - started).total_seconds()
    report["run"] = {
        "days": args.days,
        "m1_bars": len(m1),
        "from": m1[0]["time"],
        "to": m1[-1]["time"],
        "elapsed_seconds": round(elapsed, 1),
    }

    run_id = datetime.now().strftime("%Y%m%d%H%M%S") + f"_sweep_{args.days}d"
    out_dir = write_report(report, run_id)

    print(f"\n=== Backtest liquidity_sweep ({args.days} j, {elapsed:.0f}s) ===")
    for key in (
        "evaluations",
        "signals",
        "trades",
        "win_rate",
        "expectancy_r",
        "total_r",
        "profit_factor",
        "max_drawdown_pct",
        "final_equity",
    ):
        print(f"{key:>18}: {report.get(key)}")
    print(f"{'exit_reasons':>18}: {report.get('exit_reasons')}")
    print(f"{'rapport':>18}: {out_dir}")
    print("\nTop raisons de HOLD:")
    for reason, count in list(report.get("hold_reasons", {}).items())[:8]:
        print(f"  {count:>7}  {reason}")


if __name__ == "__main__":
    asyncio.run(main())
