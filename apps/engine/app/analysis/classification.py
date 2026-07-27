"""Classification post-trade : qualité de la DÉCISION vs qualité du RÉSULTAT.

Principe (cahier des charges de la refonte) :
- une perte normale qui a respecté toutes les règles n'est PAS une erreur
  (NORMAL_STATISTICAL_LOSS -> GOOD_DECISION_BAD_RESULT) ;
- un gain obtenu par chance (position presque stoppée avant de se retourner)
  est une BAD_DECISION_GOOD_RESULT : on ne renforce pas ce comportement ;
- la décision correcte ne se juge PAS sur un trade individuel.

v1 volontairement conservatrice : elle ne s'appuie que sur des mesures
objectives disponibles (R, MFE/MAE, RR visé, source de sortie). Les catégories
liées au setup (INVALID_SWEEP, BAD_RETEST...) viendront quand les features du
signal seront jointes à l'analyse. En cas de données insuffisantes :
INCONCLUSIVE / UNKNOWN — jamais une classification favorable par défaut.
"""

from dataclasses import dataclass

GOOD_GOOD = "GOOD_DECISION_GOOD_RESULT"
GOOD_BAD = "GOOD_DECISION_BAD_RESULT"
BAD_GOOD = "BAD_DECISION_GOOD_RESULT"
BAD_BAD = "BAD_DECISION_BAD_RESULT"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class TradeClassification:
    classification: str
    error_category: str
    explanation: str


def classify_trade(
    result_r: float | None,
    mfe_r: float | None,
    mae_r: float | None,
    risk_reward: float | None,
    exit_source: str | None,
) -> TradeClassification:
    """Classifie un trade clos à partir de ses excursions et de sa sortie."""
    if result_r is None:
        return TradeClassification(
            INCONCLUSIVE, "UNKNOWN", "Résultat en R indisponible (stop inconnu)"
        )
    rr = risk_reward if risk_reward and risk_reward > 0 else 2.0
    mfe = mfe_r if mfe_r is not None else 0.0
    mae = mae_r if mae_r is not None else 0.0
    source = (exit_source or "").upper()

    if source == "TIMEOUT":
        return TradeClassification(
            INCONCLUSIVE,
            "UNKNOWN",
            "Sortie par timeout : ni le stop ni l'objectif n'ont tranché",
        )

    if result_r > 0:
        # Gain « chanceux » : la position a frôlé le stop avant de gagner.
        if mae <= -0.85:
            return TradeClassification(
                BAD_GOOD,
                "NEAR_STOP_RECOVERY",
                f"Gagné {result_r:+.2f}R mais MAE {mae:.2f}R : le stop a été "
                "frôlé — résultat favorable, décision à ne pas renforcer",
            )
        return TradeClassification(
            GOOD_GOOD,
            "NONE",
            f"Gain {result_r:+.2f}R, MAE contenu ({mae:.2f}R)",
        )

    # -- Pertes ---------------------------------------------------------------
    if mfe >= 0.7 * rr:
        return TradeClassification(
            GOOD_BAD,
            "TARGET_TOO_AMBITIOUS",
            f"MFE {mfe:.2f}R a presque atteint l'objectif ({rr:.1f}R) avant "
            "le retournement : l'entrée était bonne, l'objectif trop loin",
        )
    if mfe >= 1.0:
        return TradeClassification(
            GOOD_BAD,
            "STOP_TOO_TIGHT",
            f"MFE {mfe:.2f}R puis retour au stop : la gestion (stop/partiel) "
            "a rendu perdant un trade qui avait fonctionné",
        )
    if mfe < 0.15:
        return TradeClassification(
            BAD_BAD,
            "LATE_ENTRY",
            f"MFE {mfe:.2f}R : le trade n'a jamais respiré — entrée tardive "
            "ou setup invalide au moment de l'exécution",
        )
    return TradeClassification(
        GOOD_BAD,
        "NORMAL_STATISTICAL_LOSS",
        f"Perte {result_r:+.2f}R dans les règles (MFE {mfe:.2f}R) : coût "
        "statistique normal de la stratégie",
    )
