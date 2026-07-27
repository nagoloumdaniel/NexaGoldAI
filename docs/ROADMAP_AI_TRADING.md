# ROADMAP — REFONTE SCALPING HYBRIDE IA ADAPTATIVE (XAUUSD)

Dérivée de [AUDIT_BOT_TRADING.md](AUDIT_BOT_TRADING.md) (2026-07-27).
Branche de travail : `feature/ai-adaptive-scalping-engine`.

Règles non négociables pendant toute la migration :

- modes autorisés : BACKTEST / SHADOW / PAPER (compte démo MT5) — le réel reste
  verrouillé dans le code et la config ;
- l'IA n'écrit jamais les limites de risque, ne déplace jamais un stop en
  défaveur, aucune martingale/grid/moyennage ;
- promotion de modèle exclusivement manuelle ;
- migrations Prisma additives uniquement (aucune donnée historique perdue) ;
- aucun secret dans le code ni dans git ;
- rappel projet : aucun edge net démontré sur 2023-2026 — l'objectif de la
  refonte est de construire l'infrastructure de démonstration, pas de
  « promettre » un edge.

---

## Phase 0 — Sauvegarde et point de départ

- [x] Vérifier l'état git (arbre propre au commit `c8119a1`)
- [x] Créer la branche `feature/ai-adaptive-scalping-engine`
- [x] Vérifier l'absence de secrets trackés (audit historique complet : propre)
- [x] Documenter le commit de départ dans l'audit

## Phase 1 — Audit

- [x] Explorer l'arborescence complète (moteur, API, web, scripts, infra)
- [x] Lire les modules critiques du moteur (broker, trader, stratégie, risque, learning)
- [x] Audit API NestJS (endpoints, Prisma, Telegram, sécurité, tests)
- [x] Audit web/infra (dashboard, scripts Windows, Docker, secrets, CI)
- [x] Rédiger `docs/AUDIT_BOT_TRADING.md`
- [x] Rédiger `docs/ROADMAP_AI_TRADING.md` (ce fichier)
- [ ] Faire valider le diagnostic et l'ordre des phases par l'opérateur

## Phase 2 — Fondations et corrections P0

- [x] Suite pytest introduite (`apps/engine/tests/`, 21 tests risque/kill switch, sans broker ni DB) — pytest ajouté aux dépendances
- [x] Dépendances Python épinglées (`requirements.lock`, marqueur win32 conservé) + ruff (E4/E7/E9/F/B) en CI ; mypy restant
- [ ] mypy (typage statique Python)
- [ ] Convertir `tests_manual/*` en suite pytest exécutable en une commande
- [ ] Config centralisée versionnée (YAML `configs/xauusd_scalping.yaml` + surcharge env) sans casser `Settings` pydantic
- [x] Correctif P0 risque : perte quotidienne réelle = pertes réalisées du jour (DB, `TradeRepository.risk_stats`) + flottant, fail-closed sans stats, testée
- [x] Limites hebdo + pertes consécutives + cooldown centralisé (15/60 min) dans le RiskManager
- [ ] Plafond d'exposition notionnelle dans le RiskEngine
- [x] Kill switch dynamique (`risk/kill_switch.py`) : persisté, causes historisées, verrouillage auto sur limites jour/semaine/série, endpoints `GET /risk/status`, `POST /risk/lock`, `POST /risk/unlock?reason=` (raison obligatoire), état corrompu = verrouillage préventif
- [ ] Notification Telegram sur verrouillage du kill switch (nécessite le canal moteur→API, phase 12)
- [ ] Idempotence des ordres : `signal_id`/`decision_id`/`client_order_id`, garde anti-double-envoi sur retry
- [x] Sécurité API NestJS (1er palier) : CORS strict par défaut (3002), écoute 127.0.0.1 par défaut (`API_HOST` pour surcharger), `.env.example` corrigé
- [x] Sécurité API NestJS (2e palier) : `ApiKeyGuard` (x-api-key / `API_KEY`) sur les 5 routes mutantes, câblage dashboard (`NEXT_PUBLIC_API_KEY`) et `stop-auto.ps1`
- [x] Sécurité moteur FastAPI : jeton `ENGINE_API_TOKEN` sur les 11 routes POST (test garantissant qu'aucune route POST n'est oubliée), transmis par le proxy NestJS
- [x] `ValidationPipe` global (whitelist/forbidNonWhitelisted/transform) + DTO `ResolveTradeDto` + clamp de pagination borné
- [x] `/health` API : 503 quand la DB est injoignable ; erreurs proxy moteur journalisées (fin des `catch {}` muets)
- [ ] Health checks moteur enrichis : fraîcheur données, horloge vs broker, latence, état terminal
- [x] Corriger `analytics()` : courbe d'équité = 500 snapshots les plus récents (agrégats SQL restants à faire)
- [x] Retirer la promotion automatique de champion et le hot-swap silencieux : `retrain()` enregistre un CANDIDAT, promotion manuelle via `POST /learning/promote?version=` (avec indice de rollback)
- [x] Nettoyage : `.vscode/PythonImportHelper*.json` retiré du suivi git + ignoré ; `FRONTEND_URL` corrigé 3000→3002
- [x] `.env.example` web versionné (exception `.gitignore` ajoutée)
- [ ] Nettoyage restant : ports 3000→3002 dans README/start.ps1, README réaligné (JWT/WebSockets/PyTorch fantômes)
- [x] CI GitHub Actions : lint + typecheck + tests des 3 apps (sans broker, sans secrets, jamais d'ordre)

## Phase 3 — Données

- [x] Ingestion M1 (INGEST_GRANULARITIES=M1,M5,M15,M30,H1 ; M3 dérivable de M1)
- [x] `data/validator.py` : trous (week-end exclu), bougies malformées, doublons/désordre, données figées/périmées, score 0..1 + `GET /data/quality?source=broker|db` — 10 tests
- [ ] Divergence entre timeframes (cohérence M5 vs M15/H1) et persistance du score qualité
- [ ] Table `market_snapshots` (migration Prisma additive) : bid/ask/spread + features au moment du signal
- [ ] Collecte du spread en continu (distribution par heure → seuils calibrés, médiane pour la garde)
- [ ] Backfill Dukascopy M1 profond pour le backtest évènementiel

## Phase 4 — Stratégie déterministe LIQUIDITY_SWEEP_TREND_CONTINUATION

- [ ] `strategy_v2/market_structure.py` : sommets/creux, HH/HL/LH/LL, BOS, CHoCH (H1 contexte, M15 structure)
- [ ] `strategy_v2/levels.py` : PDH/PDL, open journalier, high/low de session, égalités de sommets/creux
- [ ] `strategy_v2/liquidity_sweep.py` : détection sweep (profondeur, vitesse de réintégration, volume)
- [ ] `strategy_v2/retest_detector.py` : bougie de rejet, micro-CHoCH M1, retest dans la fenêtre
- [ ] `strategy_v2/state_machine.py` : états IDLE→…→SYSTEM_LOCKED, transitions horodatées/persistées/testées, transition interdite = erreur contrôlée
- [ ] Sessions de trading (Londres/NY configurables, éviter open/close) — logique moteur, pas seulement planificateur Windows
- [ ] Règles d'invalidation complètes (mouvement étendu, réintégration non confirmée, retest tardif…)
- [ ] Signal candidat = contrat structuré (entrée/stop/objectif théoriques, expiration, setup_type) → table `signals`
- [ ] Tests unitaires sur données synthétiques ET extraits réels rejoués

## Phase 5 — Filtre fondamental

- [x] Interface abstraite `EconomicCalendarProvider` + provider ForexFactory (flux public, parsing défensif, tolère un flux partiel)
- [x] Config fenêtres avant/après par importance (HIGH 30/20 min, MEDIUM 10/10) sur devises configurables (USD par défaut)
- [x] **Fail-closed** : calendrier jamais chargé ou plus vieux que `NEWS_MAX_AGE_MINUTES` → statut `news_blocked`, aucun nouvel ordre (les clôtures restent permises)
- [x] Câblage Trader + `GET /fundamental/status` (cache, verdict, annonces 24 h) ; vérifié en réel (FOMC 2026-07-29 détecté)
- [x] Tests (fenêtres, fuseaux via offsets ISO, absence de données, refresh, cache conservé sur panne)
- [ ] Deuxième provider de secours (redondance de source)

## Phase 6 — Moteur de risque durci (suite de la phase 2)

- [ ] Config `risk` prudente par défaut (0.10 % par trade, 0.75 %/jour, 2 %/semaine, 1 position, 3 trades/session, cooldowns) — versionnée
- [ ] Sizing complet : contraintes symbole (min/max/pas de lot, valeur du point, devise du compte) testé sur paramètres variés
- [ ] Retrait du pilotage de `position_size` par le tuner : l'IA propose ≤ 1.0, le RiskEngine décide et journalise
- [ ] Table `risk_decisions` (migration) : chaque approbation/refus avec raison et version de config
- [ ] Déclencheurs kill switch automatiques : perte jour, pertes consécutives, données invalides, MT5 déconnecté, spread/latence critiques, désync horloge, incohérence positions
- [ ] Tests exhaustifs du RiskEngine (unitaires + intégration)

## Phase 7 — Exécution MT5 durcie + paper broker

- [ ] `resolve_supported_filling_mode(symbol_info)` : refus si aucun mode fiable, journalisation, tests unitaires
- [ ] Validation pré-ordre complète (stop level, freeze level, marge, expiration signal, kill switch, cohérence décision/ordre)
- [ ] Mesure du slippage réel (prix demandé vs exécuté) persistée par ordre
- [ ] Réconciliation périodique automatique avec blocage des nouveaux ordres en cas d'écart + alerte
- [ ] Paper broker simulé local (`execution/paper_broker.py`) pour recherche/backtest : bid/ask, spread variable, slippage, latence, rejets, fills ambigus pessimistes
- [ ] Tables `orders` enrichies (migration) : client_order_id, retcode, filling mode, slippage, coûts

## Phase 8 — Mémoire et journal

- [ ] Migrations : `signals`, `ai_decisions`, `trade_results` (MFE/MAE/coûts), `trade_errors`, `model_versions`, `system_events`
- [ ] Labels par barrière (TARGET_FIRST / STOP_FIRST / TIMEOUT / AMBIGUOUS pessimiste) calculés sur M1
- [ ] Pipeline post-trade asynchrone : prédiction vs résultat, MFE/MAE, coûts, respect des règles, classification (GOOD/BAD_DECISION × GOOD/BAD_RESULT), cause racine
- [ ] Recherche de trades similaires (régime, session, volatilité, profondeur sweep…) avec seuil minimal d'échantillons
- [ ] Analyse contrefactuelle hors ligne (hypothèses seulement, jamais d'auto-application)

## Phase 9 — Modèles IA (hors ligne uniquement)

- [ ] Pipeline de features versionné (techniques, structure, liquidité, temporelles) avec garanties anti-fuite testées
- [ ] Modèle de régime v2 (LightGBM/HMM comparés hors échantillon) — sorties probabilisées
- [ ] Modèle de qualité de signal : P(TP avant SL), EV nette en R, incertitude, calibration (Brier/reliability)
- [ ] Modèle de coût d'exécution (spread attendu, slippage, latence → coût en R)
- [ ] Détecteur d'anomalies (spread extrême, données figées, hors-distribution) → SYSTEM_LOCKED
- [ ] Seuils configurables `ai_filter` (min_probability, min_ev_r, max_uncertainty) ; fallback modèle en erreur = REJECT
- [ ] Entraînement via commande séparée (`python -m app.learning.training_pipeline`), jamais dans le processus live

## Phase 10 — Backtesting réaliste

- [ ] Moteur évènementiel pour stratégies à règles (rejouable sur M1) : bid/ask, spread variable par heure, slippage, latence, rejets, stop/freeze levels, annonces
- [ ] Walk-forward + purge + embargo pour l'évaluation des modèles sur signaux candidats
- [ ] Tests de robustesse (coûts ×2, features dégradées, périodes par régime)
- [ ] Rapports `reports/backtests/<RUN_ID>/` (JSON + trades.csv + equity + HTML)
- [ ] Backtest de la stratégie sweep AVANT tout paper trading élargi
- [ ] Tests anti-fuite du moteur de backtest (aucune bougie future, reproductibilité seed)

## Phase 11 — Champion/challenger et gouvernance

- [ ] Registre étendu : statuts RESEARCH/CANDIDATE/SHADOW/CHAMPION/REJECTED/ROLLED_BACK/ARCHIVED
- [ ] Shadow mode : le challenger évalue en parallèle sans jamais envoyer d'ordre ; divergences journalisées
- [ ] Critères de promotion codifiés + action manuelle explicite (CLI/endpoint protégé)
- [ ] Rollback immédiat conservant l'ancien champion
- [ ] Détection de dérive (features, prédictions, spreads, coûts, fréquence signaux) → WARNING/PAPER_ONLY/SYSTEM_LOCKED, sans réentraînement auto

## Phase 12 — Interface et notifications

- [ ] Telegram évènementiel : démarrage/arrêt, connexion MT5, kill switch, anomalie, dérive, signal accepté/refusé important, position fermée, challenger prêt (jamais de secret)
- [ ] Dashboard : page Risque (limites, expositions, kill switch, journal des blocages)
- [ ] Dashboard : page Erreurs (classification post-trade, recommandations, résolution)
- [ ] Dashboard : gouvernance modèles (promotion/rollback protégés), comparaison backtests
- [ ] Les 10 composants front muets affichent l'état « API injoignable »
- [ ] Rapport quotidien enrichi (décisions IA, raisons de refus, coûts, drawdown cohérent)

## Phase 13 — Qualité finale

- [ ] Suite de tests complète (unitaires, intégration sans ordre réel, sécurité, backtest) verte en CI
- [ ] Tests de sécurité : impossibilité pour l'IA de modifier le risque, impossibilité de passer en réel sans double action explicite, kill switch, idempotence
- [ ] Documentation : README à jour + `docs/ARCHITECTURE / STRATEGY / AI_MODELS / RISK_MANAGEMENT / BACKTESTING / PAPER_TRADING / MODEL_GOVERNANCE / MT5_EXECUTION / INCIDENT_RESPONSE / CHANGELOG` + `.env.example` complets
- [ ] Scripts d'enregistrement des tâches planifiées versionnés (`Register-ScheduledTask`)
- [ ] Rapport final (existant/conservé/modifié/ajouté/restant, commandes exactes d'exploitation)

---

## Ordre de traitement des risques immédiats (extrait de l'audit §6)

1. Limite de perte quotidienne réelle (Phase 2)
2. Auth + CORS + validation API (Phase 2)
3. Filtre d'annonces fail-closed (Phase 5, avancé si le paper reste actif)
4. Fin de la promotion automatique de champion (Phase 2)
5. Idempotence des ordres (Phase 2)
