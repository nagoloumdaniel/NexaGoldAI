"""Read-only exit-policy ablation for the expected-return paper strategy."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.research.dataset import load_candles
from app.research.expected_return import (
    build_expected_return_dataset,
    run_nested_walk_forward,
)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def _pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _score(report: dict[str, Any]) -> float:
    aggregate = report["aggregate"]
    severe = report["cost_stress"]["severe_costs"]["pnl"]
    pf = aggregate["profit_factor"] or 0.0
    severe_pf = severe["profit_factor"] or 0.0
    robustness_penalty = 0.0
    if report["robustness"]["decision"] != "PROMOTE_TO_PAPER_TRADING":
        robustness_penalty += 1.0
    if severe["total_return"] <= 0 or severe_pf <= 1.0:
        robustness_penalty += 1.5
    return (
        aggregate["sharpe_annualised"]
        + 2.0 * max(pf - 1.0, 0.0)
        + max(severe_pf - 1.0, 0.0)
        + aggregate["total_return"]
        + aggregate["max_drawdown"]
        + 0.2 * report["robustness"]["profitable_folds"]
        - 0.35 * report["robustness"]["losing_folds"]
        - robustness_penalty
    )


def _variant(name: str, **kwargs: Any) -> dict[str, Any]:
    return {"name": name, **kwargs}


def _variant_summary(variant: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    aggregate = report["aggregate"]
    severe = report["cost_stress"]["severe_costs"]["pnl"]
    return {
        "name": variant["name"],
        "horizon": variant["horizon"],
        "exit_policy": variant["exit_policy"],
        "risk_reward_ratio": variant["risk_reward_ratio"],
        "trailing_activation_r": variant.get("trailing_activation_r"),
        "score": _score(report),
        "trades": aggregate["trades"],
        "total_return": aggregate["total_return"],
        "sharpe_annualised": aggregate["sharpe_annualised"],
        "profit_factor": aggregate["profit_factor"],
        "max_drawdown": aggregate["max_drawdown"],
        "expectancy_r": aggregate["expectancy_r"],
        "winner_profit_capture_ratio": aggregate["winner_profit_capture_ratio"],
        "giveback_ratio": aggregate["giveback_ratio"],
        "stop_loss_rate": aggregate["stop_loss_rate"],
        "take_profit_rate": aggregate["take_profit_rate"],
        "trailing_stop_rate": aggregate["trailing_stop_rate"],
        "horizon_exit_rate": aggregate["horizon_exit_rate"],
        "profitable_folds": report["robustness"]["profitable_folds"],
        "losing_folds": report["robustness"]["losing_folds"],
        "severe_total_return": severe["total_return"],
        "severe_profit_factor": severe["profit_factor"],
        "decision": report["robustness"]["decision"],
    }


def _write_markdown(path: Path, summaries: list[dict[str, Any]]) -> None:
    ranked = sorted(summaries, key=lambda item: item["score"], reverse=True)
    lines = [
        "# Ablation sorties expected-return paper",
        "",
        "Classement par score robuste: Sharpe, PF, stress couts, drawdown et stabilite des plis.",
        "",
        "| rang | variante | horizon | sortie | rendement | Sharpe | PF | DD max | stress severe | capture gagnants | SL | TP | trailing | horizon | plis | decision |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for rank, row in enumerate(ranked, start=1):
        exit_label = row["exit_policy"]
        if row["exit_policy"] == "FIXED_BRACKET":
            exit_label += f" {row['risk_reward_ratio']}R"
        if row["exit_policy"] == "TRAILING_STOP":
            exit_label += f" act {row['trailing_activation_r']}R"
        lines.append(
            "| {rank} | {name} | {horizon} | {exit_label} | {ret} | {sharpe} | {pf} | {dd} | {stress} / PF {spf} | {capture} | {sl} | {tp} | {trail} | {horizon_rate} | {pos}/{neg} | {decision} |".format(
                rank=rank,
                name=row["name"],
                horizon=row["horizon"],
                exit_label=exit_label,
                ret=_pct(row["total_return"]),
                sharpe=_num(row["sharpe_annualised"]),
                pf=_num(row["profit_factor"]),
                dd=_pct(row["max_drawdown"]),
                stress=_pct(row["severe_total_return"]),
                spf=_num(row["severe_profit_factor"]),
                capture=_pct(row["winner_profit_capture_ratio"]),
                sl=_pct(row["stop_loss_rate"]),
                tp=_pct(row["take_profit_rate"]),
                trail=_pct(row["trailing_stop_rate"]),
                horizon_rate=_pct(row["horizon_exit_rate"]),
                pos=row["profitable_folds"],
                neg=row["losing_folds"],
                decision=row["decision"],
            )
        )
    best = ranked[0]
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- Meilleure variante historique: `{best['name']}`.",
            f"- Rendement: {_pct(best['total_return'])}, Sharpe {_num(best['sharpe_annualised'])}, PF {_num(best['profit_factor'])}, DD {_pct(best['max_drawdown'])}.",
            f"- Stress severe: {_pct(best['severe_total_return'])}, PF {_num(best['severe_profit_factor'])}.",
            "",
            "## Limites",
            "",
            "- Les variantes sont comparees sur OHLC H1, avec seuil choisi dans la validation de chaque pli.",
            "- Ce rapport ne change pas le modele paper actif.",
            "- Toute promotion doit passer par paper trading prospectif et couts reels journalises.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ablation read-only des sorties")
    parser.add_argument("--granularity", default="H1")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--cost-bps-per-side", type=float, default=1.5)
    parser.add_argument("--financing-bps-per-day", type=float, default=1.6)
    parser.add_argument("--target-annual-volatility", type=float, default=0.15)
    parser.add_argument("--stop-loss-pct", type=float, default=0.005)
    parser.add_argument("--stop-loss-atr-multiplier", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    variants = [
        _variant("fixed_rr2_h24", horizon=24, risk_reward_ratio=2.0, exit_policy="FIXED_BRACKET"),
        _variant("fixed_rr3_h24_current", horizon=24, risk_reward_ratio=3.0, exit_policy="FIXED_BRACKET"),
        _variant("fixed_rr4_h24", horizon=24, risk_reward_ratio=4.0, exit_policy="FIXED_BRACKET"),
        _variant("fixed_rr3_h12", horizon=12, risk_reward_ratio=3.0, exit_policy="FIXED_BRACKET"),
        _variant("fixed_rr3_h36", horizon=36, risk_reward_ratio=3.0, exit_policy="FIXED_BRACKET"),
        _variant(
            "trailing_act1_h24",
            horizon=24,
            risk_reward_ratio=0.0,
            exit_policy="TRAILING_STOP",
            trailing_activation_r=1.0,
        ),
        _variant(
            "trailing_act0_5_h24",
            horizon=24,
            risk_reward_ratio=0.0,
            exit_policy="TRAILING_STOP",
            trailing_activation_r=0.5,
        ),
    ]

    settings = get_settings()
    candles_cache: dict[int, tuple[Any, list[str]]] = {}
    candle_frame = asyncio.run(load_candles(settings, args.granularity))
    if candle_frame.empty or len(candle_frame) < 1000:
        raise SystemExit(f"Donnees insuffisantes ({len(candle_frame)} bougies)")

    reports = []
    summaries = []
    for variant in variants:
        horizon = int(variant["horizon"])
        if horizon not in candles_cache:
            candles_cache[horizon] = build_expected_return_dataset(candle_frame, horizon)
        data, feature_columns = candles_cache[horizon]
        report = run_nested_walk_forward(
            data,
            feature_columns,
            horizon=horizon,
            n_splits=args.folds,
            granularity=args.granularity,
            cost_bps_per_side=args.cost_bps_per_side,
            financing_bps_per_day=args.financing_bps_per_day,
            direction_mode="LONG_ONLY",
            target_annual_volatility=args.target_annual_volatility,
            stop_loss_pct=args.stop_loss_pct,
            stop_loss_atr_multiplier=args.stop_loss_atr_multiplier,
            risk_reward_ratio=float(variant["risk_reward_ratio"]),
            exit_policy=str(variant["exit_policy"]),
            trailing_activation_r=float(variant.get("trailing_activation_r", 1.0)),
        )
        report["variant"] = variant
        reports.append(report)
        summaries.append(_variant_summary(variant, report))

    output_dir = args.output_dir or (
        MODELS_DIR / args.granularity / "expected_return_paper"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "data_range": [str(candle_frame.index[0]), str(candle_frame.index[-1])],
        "candles": int(len(candle_frame)),
        "summaries": sorted(summaries, key=lambda item: item["score"], reverse=True),
        "reports": reports,
    }
    json_path = output_dir / "exit_ablation.json"
    md_path = output_dir / "exit_ablation.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(md_path, summaries)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
