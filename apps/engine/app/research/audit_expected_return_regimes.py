"""Read-only regime audit for the expected-return paper strategy."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import get_settings
from app.research.dataset import load_candles
from app.research.expected_return import (
    build_expected_return_dataset,
    run_nested_walk_forward,
)
from app.research.regime_validation import build_historical_regime_features
from app.signals.regime import classify_regime

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

_REGIME_INPUT_COLUMNS = {
    "momentum_12": "_regime_momentum_12",
    "trend_strength": "_regime_trend_strength",
    "zscore_20": "_regime_zscore_20",
    "volatility_ratio_5_20": "_regime_volatility_ratio_5_20",
    "atr_pct_14": "_regime_atr_pct_14",
}


def _pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _summary_from_row(row: pd.Series) -> dict[str, Any]:
    summary: dict[str, Any] = {"data_quality_score": 1.0, "warnings": []}
    for field, column in _REGIME_INPUT_COLUMNS.items():
        value = row.get(column)
        summary[field] = None if pd.isna(value) else float(value)
    return summary


def add_regime_annotations(candles: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    regime_features = build_historical_regime_features(candles).reindex(data.index)
    enriched = data.join(regime_features)
    names = []
    trends = []
    volatilities = []
    confidences = []
    for _, row in enriched.iterrows():
        regime = classify_regime(_summary_from_row(row))
        names.append(regime["regime"])
        trends.append(regime["trend"])
        volatilities.append(regime["volatility"])
        confidences.append(regime["confidence"])
    enriched["_regime_name"] = names
    enriched["_regime_trend"] = trends
    enriched["_regime_volatility"] = volatilities
    enriched["_regime_confidence"] = confidences
    return enriched


def _base_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "n_splits": args.folds,
        "granularity": args.granularity,
        "cost_bps_per_side": args.cost_bps_per_side,
        "financing_bps_per_day": args.financing_bps_per_day,
        "direction_mode": "LONG_ONLY",
        "target_annual_volatility": args.target_annual_volatility,
        "stop_loss_pct": args.stop_loss_pct,
        "stop_loss_atr_multiplier": args.stop_loss_atr_multiplier,
        "risk_reward_ratio": args.risk_reward_ratio,
        "exit_policy": "FIXED_BRACKET",
    }


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    aggregate = report["aggregate"]
    severe = report["cost_stress"]["severe_costs"]["pnl"]
    return {
        "trades": aggregate["trades"],
        "total_return": aggregate["total_return"],
        "sharpe_annualised": aggregate["sharpe_annualised"],
        "profit_factor": aggregate["profit_factor"],
        "max_drawdown": aggregate["max_drawdown"],
        "expectancy_r": aggregate["expectancy_r"],
        "winner_profit_capture_ratio": aggregate["winner_profit_capture_ratio"],
        "stop_loss_rate": aggregate["stop_loss_rate"],
        "take_profit_rate": aggregate["take_profit_rate"],
        "horizon_exit_rate": aggregate["horizon_exit_rate"],
        "profitable_folds": report["robustness"]["profitable_folds"],
        "losing_folds": report["robustness"]["losing_folds"],
        "severe_total_return": severe["total_return"],
        "severe_profit_factor": severe["profit_factor"],
        "decision": report["robustness"]["decision"],
    }


def _filter_summary(name: str, report: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    row = _compact(report)
    severe_pf = row["severe_profit_factor"] or 0.0
    baseline_severe_pf = baseline["severe_profit_factor"] or 0.0
    row.update(
        {
            "filter": name,
            "return_delta": row["total_return"] - baseline["total_return"],
            "sharpe_delta": row["sharpe_annualised"] - baseline["sharpe_annualised"],
            "drawdown_delta": row["max_drawdown"] - baseline["max_drawdown"],
            "severe_return_delta": row["severe_total_return"]
            - baseline["severe_total_return"],
            "severe_pf_delta": severe_pf - baseline_severe_pf,
            "robust_improvement": (
                row["decision"] == "PROMOTE_TO_PAPER_TRADING"
                and row["total_return"] > baseline["total_return"]
                and row["sharpe_annualised"] >= baseline["sharpe_annualised"]
                and row["severe_total_return"] > baseline["severe_total_return"]
                and severe_pf >= baseline_severe_pf
                and row["max_drawdown"] >= baseline["max_drawdown"]
            ),
        }
    )
    return row


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    baseline = payload["baseline"]
    aggregate = payload["baseline_report"]["aggregate"]
    filters = payload["filter_tests"]
    lines = [
        "# Audit regimes expected-return paper",
        "",
        "## Baseline",
        "",
        f"- Trades: {baseline['trades']}",
        f"- Rendement: {_pct(baseline['total_return'])}",
        f"- Sharpe: {_num(baseline['sharpe_annualised'])}",
        f"- PF: {_num(baseline['profit_factor'])}",
        f"- DD max: {_pct(baseline['max_drawdown'])}",
        f"- Stress severe: {_pct(baseline['severe_total_return'])}, PF {_num(baseline['severe_profit_factor'])}",
        "",
        "## Performance par regime d'entree",
        "",
        "| regime | trades | rendement compose | PF | win rate | expectancy R | capture gagnants | SL | TP | horizon |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for regime, row in sorted(
        aggregate["by_entry_regime"].items(),
        key=lambda item: item[1]["trades"],
        reverse=True,
    ):
        lines.append(
            "| {regime} | {trades} | {ret} | {pf} | {win} | {er} | {cap} | {sl} | {tp} | {horizon} |".format(
                regime=regime,
                trades=row["trades"],
                ret=_pct(row["compounded_return"]),
                pf=_num(row["profit_factor"]),
                win=_pct(row["win_rate"]),
                er=_num(row["expectancy_r"]),
                cap=_pct(row["winner_profit_capture_ratio"]),
                sl=_pct(row["stop_loss_rate"]),
                tp=_pct(row["take_profit_rate"]),
                horizon=_pct(row["horizon_exit_rate"]),
            )
        )
    lines.extend(
        [
            "",
            "## Tests de filtre",
            "",
            "| filtre | trades | rendement | Sharpe | PF | DD | stress severe | delta rendement | delta stress | decision | verdict |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in sorted(filters, key=lambda item: item["severe_return_delta"], reverse=True):
        verdict = "CANDIDAT" if row["robust_improvement"] else "REJETE"
        lines.append(
            "| {filter} | {trades} | {ret} | {sharpe} | {pf} | {dd} | {stress} / PF {spf} | {dret} | {dstress} | {decision} | {verdict} |".format(
                filter=row["filter"],
                trades=row["trades"],
                ret=_pct(row["total_return"]),
                sharpe=_num(row["sharpe_annualised"]),
                pf=_num(row["profit_factor"]),
                dd=_pct(row["max_drawdown"]),
                stress=_pct(row["severe_total_return"]),
                spf=_num(row["severe_profit_factor"]),
                dret=_pct(row["return_delta"]),
                dstress=_pct(row["severe_return_delta"]),
                decision=row["decision"],
                verdict=verdict,
            )
        )
    candidates = [row for row in filters if row["robust_improvement"]]
    lines.extend(["", "## Verdict", ""])
    if candidates:
        best = max(candidates, key=lambda item: item["severe_return_delta"])
        lines.append(
            f"- Candidat filtre: `{best['filter']}`. Il doit encore passer une validation paper."
        )
    else:
        lines.append(
            "- Aucun filtre de regime simple ne justifie une modification de la strategie paper actuelle."
        )
    lines.extend(
        [
            "- La prochaine etape utile est une analyse plus fine des regimes recents et des couts reels, pas une activation live.",
            "",
            "## Limites",
            "",
            "- Regime v1 heuristique, pas encore un modele statistique de regime.",
            "- Audit sur OHLC H1, pas sur ticks Bid/Ask.",
            "- Les filtres testes sont des exclusions simples; ils peuvent reduire l'echantillon et suradapter.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit read-only par regime")
    parser.add_argument("--granularity", default="H1")
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--cost-bps-per-side", type=float, default=1.5)
    parser.add_argument("--financing-bps-per-day", type=float, default=1.6)
    parser.add_argument("--target-annual-volatility", type=float, default=0.15)
    parser.add_argument("--stop-loss-pct", type=float, default=0.005)
    parser.add_argument("--stop-loss-atr-multiplier", type=float, default=3.0)
    parser.add_argument("--risk-reward-ratio", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    candles = asyncio.run(load_candles(settings, args.granularity))
    if candles.empty or len(candles) < 1000:
        raise SystemExit(f"Donnees insuffisantes ({len(candles)} bougies)")
    data, feature_columns = build_expected_return_dataset(candles, args.horizon)
    data = add_regime_annotations(candles, data)

    baseline_report = run_nested_walk_forward(
        data,
        feature_columns,
        horizon=args.horizon,
        **_base_kwargs(args),
    )
    baseline = _compact(baseline_report)

    filter_tests = []
    tested_filters = set()
    regimes = baseline_report["aggregate"]["by_entry_regime"]
    for regime, row in regimes.items():
        if row["trades"] < 25:
            continue
        column = f"_allow_without_{regime.lower().replace(' ', '_')}"
        data[column] = data["_regime_name"] != regime
        report = run_nested_walk_forward(
            data,
            feature_columns,
            horizon=args.horizon,
            position_filter_column=column,
            **_base_kwargs(args),
        )
        filter_tests.append(
            _filter_summary(f"exclude_regime:{regime}", report, baseline)
        )
        tested_filters.add(column)

    for trend in ("BULLISH", "BEARISH", "RANGE"):
        column = f"_allow_without_trend_{trend.lower()}"
        data[column] = data["_regime_trend"] != trend
        report = run_nested_walk_forward(
            data,
            feature_columns,
            horizon=args.horizon,
            position_filter_column=column,
            **_base_kwargs(args),
        )
        filter_tests.append(_filter_summary(f"exclude_trend:{trend}", report, baseline))
        tested_filters.add(column)

    payload = {
        "data_range": [str(candles.index[0]), str(candles.index[-1])],
        "candles": int(len(candles)),
        "baseline": baseline,
        "baseline_report": baseline_report,
        "filter_tests": filter_tests,
    }
    output_dir = args.output_dir or (
        MODELS_DIR / args.granularity / "expected_return_paper"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "regime_audit.json"
    md_path = output_dir / "regime_audit.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(md_path, payload)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
