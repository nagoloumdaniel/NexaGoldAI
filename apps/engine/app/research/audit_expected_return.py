"""Read-only MFE/MAE audit for the expected-return paper strategy."""

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


def _priority(condition: bool, fallback: str = "Moyenne") -> str:
    return "Haute" if condition else fallback


def _diagnostic_table(report: dict[str, Any]) -> list[dict[str, str]]:
    aggregate = report["aggregate"]
    severe = report["cost_stress"]["severe_costs"]["pnl"]
    losing_folds = report["robustness"]["losing_folds"]
    diagnostics = [
        {
            "identifiant": "AUD-MFE-001",
            "probleme": "Marge faible face aux couts reels",
            "symptome_observe": (
                f"Stress severe {_pct(severe['total_return'])}, "
                f"PF {_num(severe['profit_factor'])}"
            ),
            "cause_probable": "Spread, slippage, commission ou financement superieurs aux hypotheses",
            "preuves": "Le profit factor severe reste proche de 1",
            "niveau_confiance": "Eleve",
            "impact_financier": "Eleve",
            "impact_risque": "Eleve",
            "frequence": "Systemique",
            "priorite": _priority(
                severe["profit_factor"] is None or severe["profit_factor"] < 1.05,
                "Critique",
            ),
            "solution_proposee": "Journaliser couts reels et refuser les trades si spread/cout attendu mange l'edge",
            "test_validation": "Rejouer le walk-forward avec couts reels observes et stress randomise",
            "risque_regression": "Peut reduire la frequence de trades",
        },
        {
            "identifiant": "AUD-MFE-002",
            "probleme": "Robustesse recente imparfaite",
            "symptome_observe": f"{losing_folds} pli perdant sur {report['params']['folds']}",
            "cause_probable": "Changement de regime, seuil instable ou surselection historique",
            "preuves": "Le dernier pli OOS du rapport paper est negatif",
            "niveau_confiance": "Moyen",
            "impact_financier": "Moyen a eleve",
            "impact_risque": "Moyen",
            "frequence": "Par regime",
            "priorite": _priority(losing_folds > 0),
            "solution_proposee": "Segmenter MFE/MAE par regime et appliquer un kill-switch de degradation",
            "test_validation": "Walk-forward par regime + paper 100 trades clotures",
            "risque_regression": "Peut bloquer des periodes finalement rentables",
        },
        {
            "identifiant": "AUD-MFE-003",
            "probleme": "Capture des profits a verifier",
            "symptome_observe": (
                f"Capture gagnants {_pct(aggregate['winner_profit_capture_ratio'])}, "
                f"giveback {_pct(aggregate['giveback_ratio'])}"
            ),
            "cause_probable": "TP fixe 3R, horizon 24h ou absence de trailing/partiel",
            "preuves": "MFE/MAE maintenant mesure dans le simulateur",
            "niveau_confiance": "Moyen",
            "impact_financier": "Moyen",
            "impact_risque": "Moyen",
            "frequence": "Trade par trade",
            "priorite": "Haute",
            "solution_proposee": "Comparer TP 2R/3R/4R, sortie partielle et trailing ATR sans fuite future",
            "test_validation": "Ablation sorties avec meme walk-forward et memes couts",
            "risque_regression": "Peut augmenter la variance ou couper les gros gagnants",
        },
        {
            "identifiant": "AUD-MFE-004",
            "probleme": "Stops et bruit intrabar a quantifier",
            "symptome_observe": (
                f"MAE moyen {_num(aggregate['average_mae_r'])}R, "
                f"taux SL {_pct(aggregate['stop_loss_rate'])}"
            ),
            "cause_probable": "Stop ATR trop proche dans certains regimes ou entree trop precoce",
            "preuves": "MAE rapporte au risque initial disponible par trade",
            "niveau_confiance": "Moyen",
            "impact_financier": "Moyen",
            "impact_risque": "Eleve",
            "frequence": "Selon volatilite",
            "priorite": "Haute",
            "solution_proposee": "Tester stop structurel/ATR et filtre d'entree apres retest",
            "test_validation": "Comparer MAE_R, PF, drawdown et stress couts par variante",
            "risque_regression": "Stop plus large peut reduire le nombre d'unites",
        },
    ]
    return diagnostics


def _write_markdown(path: Path, report: dict[str, Any], diagnostics: list[dict[str, str]]) -> None:
    aggregate = report["aggregate"]
    severe = report["cost_stress"]["severe_costs"]["pnl"]
    lines = [
        "# Audit MFE/MAE expected-return paper",
        "",
        "## Resume",
        "",
        f"- Bougies: {report['candles']} ({report['data_range'][0]} -> {report['data_range'][1]})",
        f"- Trades OOS: {aggregate['trades']}",
        f"- Rendement net: {_pct(aggregate['total_return'])}",
        f"- Sharpe annualise: {_num(aggregate['sharpe_annualised'])}",
        f"- Profit factor: {_num(aggregate['profit_factor'])}",
        f"- Max drawdown: {_pct(aggregate['max_drawdown'])}",
        f"- Stress severe: {_pct(severe['total_return'])}, PF {_num(severe['profit_factor'])}",
        "",
        "## MFE/MAE",
        "",
        f"- MFE moyen: {_pct(aggregate['average_mfe_pct'])} ({_num(aggregate['average_mfe_r'])}R)",
        f"- MAE moyen: {_pct(aggregate['average_mae_pct'])} ({_num(aggregate['average_mae_r'])}R)",
        f"- R realise moyen: {_num(aggregate['average_realised_r'])}R",
        f"- Capture moyenne: {_pct(aggregate['profit_capture_ratio'])}",
        f"- Capture des gagnants: {_pct(aggregate['winner_profit_capture_ratio'])}",
        f"- Giveback moyen: {_pct(aggregate['giveback_ratio'])}",
        "",
        "## Sorties",
        "",
        f"- STOP_LOSS: {_pct(aggregate['stop_loss_rate'])}",
        f"- TAKE_PROFIT: {_pct(aggregate['take_profit_rate'])}",
        f"- HORIZON: {_pct(aggregate['horizon_exit_rate'])}",
        "",
        "## Diagnostic",
        "",
        "| identifiant | probleme | preuves | priorite | test de validation |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in diagnostics:
        lines.append(
            "| {identifiant} | {probleme} | {preuves} | {priorite} | {test_validation} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## Limites",
            "",
            "- Audit base sur bougies OHLC H1, pas sur ticks Bid/Ask.",
            "- Si SL et TP sont touches dans la meme bougie, le simulateur garde l'hypothese pessimiste STOP.",
            "- Les couts reels du broker (MT5) doivent encore etre journalises trade par trade.",
            "- Les resultats historiques ne suffisent pas pour une promotion live.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit MFE/MAE expected-return paper")
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
    report = run_nested_walk_forward(
        data,
        feature_columns,
        horizon=args.horizon,
        n_splits=args.folds,
        granularity=args.granularity,
        cost_bps_per_side=args.cost_bps_per_side,
        financing_bps_per_day=args.financing_bps_per_day,
        direction_mode="LONG_ONLY",
        target_annual_volatility=args.target_annual_volatility,
        stop_loss_pct=args.stop_loss_pct,
        stop_loss_atr_multiplier=args.stop_loss_atr_multiplier,
        risk_reward_ratio=args.risk_reward_ratio,
    )
    report["data_range"] = [str(candles.index[0]), str(candles.index[-1])]
    report["candles"] = int(len(candles))
    diagnostics = _diagnostic_table(report)
    audit = {"walk_forward": report, "diagnostic_table": diagnostics}

    output_dir = args.output_dir or (
        MODELS_DIR / args.granularity / "expected_return_paper"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "audit_mfe_mae.json"
    md_path = output_dir / "audit_mfe_mae.md"
    json_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    _write_markdown(md_path, report, diagnostics)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
