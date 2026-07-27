"""Entraînement hors ligne du modèle de qualité de signal (Phase 9).

Commande séparée — jamais exécutée dans le processus de trading :

  .venv\\Scripts\\python.exe -m app.learning.train_signal_quality

Pipeline :
1. charge les datasets CSV (models/liquidity_sweep/datasets/) ; `source_m1`
   distingue le déclencheur M1 fidèle du mode M5 dégradé ;
2. cible binaire : TARGET_FIRST=1 vs STOP_FIRST/AMBIGUOUS=0 (TIMEOUT et
   INVALID_DATA écartés) ;
3. tri chronologique + validation walk-forward expansive (les sous-modèles ne
   voient jamais le futur) ; prédictions hors échantillon pour les métriques ;
4. métriques honnêtes : Brier vs baseline (taux de base du TRAIN), AUC,
   calibration par déciles, et surtout l'effet ÉCONOMIQUE du filtre
   (espérance R des candidats au-dessus du seuil vs tous) ;
5. artefact versionné statut CANDIDATE : ensemble des modèles de folds
   (l'écart entre folds = incertitude d'inférence) + médianes d'imputation du
   train + meta complet. Aucune promotion automatique.

Modèle : régression logistique régularisée (pipeline scaler+LR). ~700
échantillons ne justifient rien de plus complexe ; LightGBM pourra concourir
quand le paper aura enrichi le dataset.
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.ai.signal_quality import FEATURE_ORDER, FEATURE_SPEC_VERSION, build_feature_vector

DATASETS_DIR = Path(__file__).resolve().parents[2] / "models" / "liquidity_sweep" / "datasets"
ARTIFACTS_DIR = (
    Path(__file__).resolve().parents[2] / "models" / "liquidity_sweep" / "signal_quality"
)

DECIDED = {"TARGET_FIRST": 1, "STOP_FIRST": 0, "AMBIGUOUS": 0}


def load_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        source_m1 = "_M1_" in path.name
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("outcome") not in DECIDED:
                    continue
                row["source_m1"] = 1.0 if source_m1 else 0.0
                row["_dataset"] = path.name
                rows.append(row)
    rows.sort(key=lambda r: r["signal_time"])
    return rows


def make_matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x_raw = [build_feature_vector(r) for r in rows]
    y = np.array([DECIDED[r["outcome"]] for r in rows], dtype=int)
    r_values = np.array(
        [float(r["result_r"]) if r.get("result_r") not in (None, "") else 0.0 for r in rows]
    )
    x = np.array(
        [[np.nan if v is None else v for v in vec] for vec in x_raw], dtype=float
    )
    return x, y, r_values


def make_model() -> object:
    return make_pipeline(
        StandardScaler(), LogisticRegression(C=0.5, max_iter=2000)
    )


def walk_forward(x, y, folds: int):
    """Prédictions hors échantillon + sous-modèles de chaque fold."""
    n = len(y)
    oos = np.full(n, np.nan)
    models = []
    boundaries = np.linspace(0, n, folds + 1, dtype=int)
    for k in range(1, folds):
        train_idx = np.arange(0, boundaries[k])
        test_idx = np.arange(boundaries[k], boundaries[k + 1])
        if len(np.unique(y[train_idx])) < 2 or len(test_idx) == 0:
            continue
        medians = np.nanmedian(x[train_idx], axis=0)
        x_train = np.where(np.isnan(x[train_idx]), medians, x[train_idx])
        x_test = np.where(np.isnan(x[test_idx]), medians, x[test_idx])
        model = make_model()
        model.fit(x_train, y[train_idx])
        oos[test_idx] = model.predict_proba(x_test)[:, 1]
        models.append(model)
    return oos, models


def economic_lift(probs, y, r_values, thresholds=(0.30, 0.35, 0.40)) -> dict:
    mask = ~np.isnan(probs)
    out = {
        "all": {
            "n": int(mask.sum()),
            "expectancy_r": round(float(r_values[mask].mean()), 4) if mask.any() else None,
            "hit_rate": round(float(y[mask].mean()), 4) if mask.any() else None,
        }
    }
    for t in thresholds:
        selected = mask & (probs >= t)
        out[f"p>={t}"] = {
            "n": int(selected.sum()),
            "expectancy_r": round(float(r_values[selected].mean()), 4)
            if selected.any()
            else None,
            "hit_rate": round(float(y[selected].mean()), 4) if selected.any() else None,
        }
    return out


def reliability(probs, y, bins: int = 5) -> list[dict]:
    mask = ~np.isnan(probs)
    p, t = probs[mask], y[mask]
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    rows = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        sel = (p >= lo) & (p <= hi if i == bins - 1 else p < hi)
        if sel.sum() == 0:
            continue
        rows.append(
            {
                "bucket": f"[{lo:.2f},{hi:.2f}]",
                "n": int(sel.sum()),
                "predicted": round(float(p[sel].mean()), 4),
                "observed": round(float(t[sel].mean()), 4),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Entraînement qualité de signal")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--datasets", nargs="*", help="CSV explicites (défaut: tout le dossier datasets)"
    )
    args = parser.parse_args()

    paths = (
        [Path(p) for p in args.datasets]
        if args.datasets
        else sorted(DATASETS_DIR.glob("*.csv"))
    )
    if not paths:
        raise SystemExit("Aucun dataset — lancer d'abord app.learning.dataset_builder")
    rows = load_rows(paths)
    if len(rows) < 100:
        raise SystemExit(f"Seulement {len(rows)} échantillons tranchés — insuffisant")

    x, y, r_values = make_matrix(rows)
    oos, fold_models = walk_forward(x, y, args.folds)
    mask = ~np.isnan(oos)
    if mask.sum() < 50:
        raise SystemExit("Trop peu de prédictions hors échantillon")

    base_rate = float(y[~mask].mean()) if (~mask).any() else float(y.mean())
    metrics = {
        "samples": int(len(y)),
        "oos_predictions": int(mask.sum()),
        "target_rate_oos": round(float(y[mask].mean()), 4),
        "brier": round(float(brier_score_loss(y[mask], oos[mask])), 4),
        "brier_baseline_train_rate": round(
            float(brier_score_loss(y[mask], np.full(mask.sum(), base_rate))), 4
        ),
        "log_loss": round(float(log_loss(y[mask], oos[mask], labels=[0, 1])), 4),
        "auc": round(float(roc_auc_score(y[mask], oos[mask])), 4)
        if len(np.unique(y[mask])) > 1
        else None,
        "reliability": reliability(oos, y),
        "economic_lift_oos": economic_lift(oos, y, r_values),
    }

    # Modèle final = ensemble des sous-modèles de folds (incertitude par
    # désaccord) ; médianes d'imputation calculées sur TOUT l'historique
    # d'entraînement (utilisées à l'inférence uniquement).
    medians = [float(v) for v in np.nanmedian(x, axis=0)]

    version = "v" + datetime.now().strftime("%Y%m%d%H%M%S")
    out_dir = ARTIFACTS_DIR / version
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": fold_models, "medians": medians}, out_dir / "model.joblib")
    meta = {
        "version": version,
        "status": "CANDIDATE",
        "automatic_promotion": False,
        "model_type": "logistic_regression_ensemble",
        "feature_spec": FEATURE_SPEC_VERSION,
        "features": list(FEATURE_ORDER),
        "datasets": [p.name for p in paths],
        "training_period": [rows[0]["signal_time"], rows[-1]["signal_time"]],
        "folds": args.folds,
        "metrics": metrics,
        "created_at": datetime.now().isoformat(),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Artefact CANDIDATE: {out_dir}")
    print(json.dumps({k: v for k, v in metrics.items() if k != "reliability"}, indent=2))
    print("Calibration (déciles):")
    for row in metrics["reliability"]:
        print(f"  {row['bucket']:>14} n={row['n']:>4} prédit={row['predicted']:.3f} observé={row['observed']:.3f}")


if __name__ == "__main__":
    main()
