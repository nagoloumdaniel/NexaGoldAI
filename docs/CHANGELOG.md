# CHANGELOG

Journal des changements notables. Le détail complet est dans l'historique git.

## Refonte « scalping hybride IA adaptative » — 2026-07-27/28

Branche `feature/ai-adaptive-scalping-engine`, partie du commit `c8119a1`.
Audit complet : [AUDIT_BOT_TRADING.md](AUDIT_BOT_TRADING.md) ; plan :
[ROADMAP_AI_TRADING.md](ROADMAP_AI_TRADING.md).

### Sécurité et protection du capital

- **Correctif majeur** : la limite de perte quotidienne ne voyait que le
  flottant (`solde − équité`) et ne se déclenchait donc jamais après des pertes
  réalisées. Elle s'appuie désormais sur le P&L réalisé en base + le flottant.
- Limite hebdomadaire, pertes consécutives et cooldowns imposés par le moteur
  de risque, indépendamment des stratégies.
- `RiskManager` **fail-closed** : sans statistiques fiables, il refuse.
- **Kill switch dynamique** persisté, verrouillage automatique sur limite
  atteinte, réactivation manuelle à raison obligatoire, verrouillage préventif
  si son état est illisible.
- **Filtre d'annonces économiques fail-closed** (ForexFactory) : aucune
  nouvelle entrée dans les fenêtres d'annonces ni si le calendrier est
  indisponible.
- Clé d'API sur toutes les routes mutantes (API et moteur), CORS strict,
  écoute `127.0.0.1` par défaut, `ValidationPipe` + DTO, token Telegram masqué
  dans les logs.
- Fin de la **promotion automatique** de champion : un réentraînement produit
  un candidat, la promotion est manuelle.

### Stratégie

- Nouvelle stratégie **LIQUIDITY_SWEEP_TREND_CONTINUATION** (`strategy_v2/`) :
  structure H1/M15 (swings, BOS, CHoCH), zones de liquidité M5 avec égalités,
  sweep + réintégration, shift et retest M1, sessions, machine à états à
  transitions contrôlées et historisées.
- **Bascule du paper** sur cette stratégie le 2026-07-28 (`scalp_m5` reste
  disponible en un changement de `.env`).
- `SWEEP_MIN_RISK_REWARD=3.0` calibré par backtest (RR 2 était négatif).

### Backtest et données

- **Moteur de backtest évènementiel M1** : fenêtres multi-timeframes sans
  lookahead, fill à l'ouverture suivante, demi-spread et slippage à charge,
  bracket intrabar pessimiste, rapports CSV/JSON.
- Verdict `liquidity_sweep` : **+0.12 R** d'espérance à RR 3 (PF 1.16), positif
  à coûts doublés et stable sur les deux moitiés — statut PAPER_CANDIDATE, non
  démontré statistiquement.
- **Validateur de qualité des données** (`/data/quality`) et ingestion M1.

### Mémoire et analyse

- Tables `TradeResult` (R, MFE/MAE, durée, classification), `RiskDecision`,
  `SystemEvent`.
- **Analyse post-trade** à chaque clôture et **classification** des décisions
  (bonne/mauvaise décision × bon/mauvais résultat, avec cause).
- Labels par barrière pour l'entraînement (ambigus comptés pessimistes).

### IA

- Pipeline complet : générateur de dataset, spec de features partagée,
  entraînement walk-forward calibré.
- **Modèle de qualité de signal v1 REJETÉ** (AUC 0.444, Brier pire que la
  baseline). Aucun modèle n'est branché — la stratégie déterministe décide
  seule. Détail : [AI_MODELS.md](AI_MODELS.md).

### Interface et exploitation

- Pages dashboard **`/risque`** (kill switch, consommation des limites, filtre
  d'annonces, journal des blocages) et **`/erreurs`** (répartition des
  décisions, causes, MFE/MAE, analyses post-trade).
- **Alertes Telegram évènementielles** par relais base de données : le moteur
  écrit un `SystemEvent`, l'API le relaie — kill switch verrouillé, broker
  dégradé/rétabli.
- CI GitHub Actions (lint, typecheck, tests des trois applications), lockfile
  Python, ruff, suite pytest (114 tests) et tests API réellement exécutables.

## Antérieur

- **2026-07-26** : stratégie scalp M5 multi-timeframe avec tuner adaptatif.
- **2026-07-25** : migration du broker Capital.com vers MetaTrader 5 local.
- **2026-06/07** : expected-return H1 promue paper ; le backtest 2023-2026 a
  ensuite montré qu'aucun edge net n'était démontré (le Sharpe +3.27 initial
  était un artefact).
