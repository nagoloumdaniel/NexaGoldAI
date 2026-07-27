# AUDIT COMPLET — BOT DE TRADING NEXAGOLD

Date : 2026-07-27
Commit audité : `c8119a1` (branche `feature/ai-adaptive-scalping-engine`)
Périmètre : monorepo complet (`apps/engine`, `apps/api`, `apps/web`, scripts racine, infra).

> Cet audit est le préalable à la refonte « scalping hybride IA adaptative »
> (stratégie `LIQUIDITY_SWEEP_TREND_CONTINUATION`). Aucune modification de code
> n'a été faite avant sa rédaction. Le plan d'exécution dérivé est dans
> [ROADMAP_AI_TRADING.md](ROADMAP_AI_TRADING.md).

---

## 0. Informations projet détectées (vérifiées dans le code)

| Variable | Valeur réelle détectée |
|---|---|
| PROJECT_PATH | `d:\Projets\NexaGoldAI` (monorepo 3 apps) |
| PRIMARY_SYMBOL | `XAUUSD` (configurable `SYMBOL`, suffixes broker prévus) |
| BROKER | MetaTrader 5 local (terminal Windows, paquet Python `MetaTrader5`) — Capital.com retiré le 2026-07-25 |
| TRADING_PLATFORM | MetaTrader 5 (pont IPC synchrone encapsulé async) |
| DEFAULT_MODE | Paper sur compte **démo réel MT5** (pas de simulateur local) ; `TRADING_ENABLED=false` par défaut |
| DASHBOARD | **Next.js 15 (port 3002)** — PAS Streamlit. Le prompt de refonte est adapté à cette réalité. |
| API | **NestJS 11 (port 3001)** — façade DB + proxy vers le moteur |
| MOTEUR | **FastAPI (port 8000), Python 3.14** — data, stratégie, risque, exécution, learning |
| NOTIFICATIONS | Telegram via l'API NestJS uniquement (3 rapports périodiques, aucune alerte événementielle) |
| DATABASE | PostgreSQL (Docker local port 5433), schéma **Prisma 7** ; le moteur y écrit en SQL brut `asyncpg` |
| REDIS | Déclaré (`REDIS_URL`, Docker port 6380) mais **utilisé nulle part** |
| EA MQL5 | Absent (aucun Expert Advisor ; tout passe par le pont Python) |
| CI/CD | **Absente** (aucun workflow) |
| Python | 3.14.5 ; deps : fastapi, MetaTrader5 (win32 only), asyncpg, numpy, pandas, scikit-learn, lightgbm, joblib |
| Tests | Moteur : `tests_manual/*` exécutés à la main (pas de pytest). API : starter NestJS uniquement. Web : aucun. |
| Git | Propre au démarrage ; `.env` non trackés ; `.env.example` présents (api + engine) |

Contrainte structurante : le paquet `MetaTrader5` est **Windows-only** → le moteur
tourne nativement sur ce PC (fenêtre planifiée jours ouvrés 9h-20h via tâches
Windows + scripts `start-hidden.ps1` / `stop-auto.ps1`). Non dockerisable.

---

## 1. Architecture actuelle

### 1.1 Composants et flux

```
MT5 terminal (Windows, IPC)
      │  copy_rates / order_send / positions / history_deals
      ▼
apps/engine (FastAPI :8000) ─────────────────────────────┐
  broker/mt5.py        client async normalisé (MAGIC 20260725)
  data/ingestion.py    boucle 60s → table Candle (M5,M15,M30,H1)
  strategy/scalp_mtf   votes EMA/RSI/MACD M15/M30/H1 → entrée M5
  learning/adaptive    tuner borné (état JSON local)
  risk/manager.py      % risque / positions max / perte jour (approx.)
  execution/trader.py  boucle signal 60s + moniteur profit 5s
      │ SQL brut (asyncpg)
      ▼
PostgreSQL (Candle, Trade, StrategyDecision, EquitySnapshot, User†)
      ▲ Prisma 7
apps/api (NestJS :3001)  ── proxys /dashboard/* → moteur ; crons rapports → Telegram
      ▲ REST (polling)
apps/web (Next.js :3002) ── pages dashboard (candles, décisions, trades, IA, positions…)
```
† table morte (auth jamais implémentée).

### 1.2 Flux d'un signal (état actuel)

1. `Trader.step()` toutes les 60 s ([trader.py](../apps/engine/app/execution/trader.py)) :
   réconciliation paper → clôtures expirées → filet de prise de profit → fetch
   bougies M5 + extra M15/M30/H1.
2. `ScalpM5Strategy.evaluate()` : votes de tendance par timeframe (EMA20/50,
   RSI14, MACD hist, 2 accords sur 3 requis par TF) ; alignement `min_votes`
   sans contradiction ; cooldown après perte ; 1 entrée par bougie M5 ;
   déclencheur M5 (EMA9/21, RSI7, bougie de confirmation, zones RSI14
   interdites) ; stop `max(plancher, ATR14×mult)` ; TP secours 2R.
3. Chaque évaluation → ligne `StrategyDecision` (exécutée ou non), avec
   `features` JSON et `reason` lisible.
4. Gardes d'exécution : HOLD → stop ; paper_only hors démo → stop ; marché
   fermé → stop ; spread relatif > `MAX_SPREAD_PCT` → stop ; compte MT5 non
   démo (vérifié auprès du terminal) → stop.
5. `RiskManager.review()` : kill switch, positions max (positions du bot
   uniquement : symbole+magic), perte quotidienne (approximation
   `balance - equity`), sizing = `balance × %risque / distance_stop ×
   multiplicateur stratégie`.
6. `MT5Client.create_market_order()` : conversion onces→lots (contract size,
   pas de lot, minimum), filling mode détecté depuis `symbol_info`, SL/TP
   serveur, `deviation=20`, magic, retcodes contrôlés.
7. `Trade` inséré en DB (unités réellement exécutées), décision marquée
   exécutée, bougie M5 marquée consommée.
8. Sortie : moniteur 5 s ferme dès profit net ≥ seuil appris ; sinon SL/TP
   serveur ; réconciliation `history_deals_get` rattache les clôtures et
   alimente le tuner adaptatif (`record_trade` → ajustements bornés tous les
   8 trades, journalisés avec raison).

### 1.3 Verrous de sécurité existants (à préserver)

- `TRADING_ENABLED=false` par défaut (kill switch global, vérifié dans le
  RiskManager).
- `build_strategy` refuse `scalp_m5` et `expected_return_paper` hors
  `BROKER_ENV=demo` ([factory.py](../apps/engine/app/strategy/factory.py)).
- Défense en profondeur : avant tout ordre, `account_info()` du terminal doit
  confirmer un compte démo ([trader.py:396](../apps/engine/app/execution/trader.py#L396)).
- Hot-swap automatique vers une stratégie non-paper interdit.
- Promotion live : `promotion_eligibility_status()` renvoie
  `promotion_eligible: False` en dur avec blockers explicites.
- Positions du bot isolées par magic number 20260725.
- Garde de spread avant ordre ; élargissement du stop au minimum broker AVANT
  le sizing.

### 1.4 Verdicts de recherche déjà rendus (à ne pas perdre)

- **Backtest 2023-2026 : aucun edge net démontré.** Le Sharpe +3.27 initial
  était un artefact ; à coûts réalistes toutes les configs/timeframes/macro
  testées sont négatives. Décision projet : ne jamais activer le réel sans
  nouvelle démonstration (PROJECT_STATUS.md, mémoire projet).
- Filtre de régime : validation walk-forward H1 → réduit la perte d'une
  stratégie perdante mais PF < 1 → `REJECT_LIVE_INTEGRATION`, resté read-only.
- Expected-return 24h : promu paper uniquement, remplacé depuis par scalp_m5.
- **La stratégie scalp_m5 actuelle n'a jamais été backtestée** — validation
  paper prospective uniquement (assumé dans PROJECT_STATUS.md).

---

## 2. Fonctionnalités actuelles — classification

Légende : FONCTIONNEL / PARTIELLEMENT FONCTIONNEL / MOCKÉ / ABSENT / DÉFECTUEUX / À SÉCURISER / À REFACTORISER

### Moteur (apps/engine)

| Fonctionnalité | État | Détail |
|---|---|---|
| Connexion MT5 (init, reconnexion, symbol_select, verrou démo) | FONCTIONNEL | [mt5.py](../apps/engine/app/broker/mt5.py) ; offset UTC configurable |
| Détection filling mode | PARTIELLEMENT FONCTIONNEL | IOC→FOK→RETURN depuis `symbol_info.filling_mode` ; pas de refus si aucun mode fiable, pas de test unitaire |
| Ordres marché (lots, SL/TP serveur, retcodes) | FONCTIONNEL | Conversion onces↔lots à la frontière ; unités exécutées journalisées |
| Ingestion bougies M5/M15/M30/H1 + backfill MT5/Dukascopy + resample | FONCTIONNEL | Idempotent (upsert clé composite) |
| Données macro (EURUSD) + taux réels FRED | FONCTIONNEL | Utilisées par la recherche, pas par scalp_m5 |
| Stratégie scalp M5 multi-timeframe | FONCTIONNEL (non validé) | Règles déterministes, features journalisées ; **jamais backtestée** |
| Tuner adaptatif borné | FONCTIONNEL | Bornes dures, journal des ajustements, état persisté ; fenêtre 30 trades |
| RiskManager | PARTIELLEMENT FONCTIONNEL | Perte quotidienne ≈ `balance - nav` : fausse dès qu'une perte est **réalisée** (equity rejoint balance) → limite jour inopérante après clôture ; pas de limite hebdo, pas de pertes consécutives, pas de cooldown centralisé (délégué à la stratégie), pas de plafond d'exposition |
| Kill switch | PARTIELLEMENT FONCTIONNEL | Statique (env var, redémarrage requis) ; aucun déclenchement automatique (drawdown, anomalie, déconnexion, dérive) ; pas de notification |
| Machine à états de stratégie | ABSENT | Logique linéaire dans `step()` ; transitions non tracées |
| Détection structure (BOS/CHoCH, sweep, réintégration, retest) | ABSENT | Rien de tel ; stratégie actuelle = indicateurs classiques |
| Filtre fondamental / calendrier économique | ABSENT | Aucune fenêtre d'interdiction autour des annonces (NFP, CPI, FOMC) — risque majeur pour un scalp XAUUSD |
| Sessions de trading (Londres/NY, éviter open/close) | ABSENT | La fenêtre 9h-20h est un planificateur Windows, pas une logique de session |
| Modèle de régime | PARTIELLEMENT FONCTIONNEL | Heuristique déterministe explicable ([regime.py](../apps/engine/app/signals/regime.py)) ; validation historique → REJECT ; non branché sur scalp_m5 |
| Modèle qualité de signal (P(TP avant SL), EV nette, incertitude) | ABSENT | `structured.py` expose des champs mais `uncertainty = 1 - confidence` (placeholder assumé), pas de calibration |
| Modèle de coût d'exécution | ABSENT | Spread observé mais pas modélisé ; slippage jamais mesuré (`slippage_estimate: None`) |
| Détecteur d'anomalies | ABSENT | Pas de détection spread extrême / données figées / horloge désynchronisée / divergence timeframes |
| Classification des erreurs post-trade | ABSENT | Aucune analyse post-trade ; le tuner ne voit que le PnL |
| Labels MFE/MAE / barrières par trade | ABSENT en production | Existe uniquement en recherche (audit MFE/MAE de l'ancienne stratégie) |
| Backtesting | PARTIELLEMENT FONCTIONNEL | Walk-forward LightGBM honnête (embargo, coûts bps, intrabar stop-first pessimiste) mais : coûts en bps constants (pas de spread variable/slippage/latence), **inapplicable à scalp_m5** (aucun backtest de règles évènementielles), rapports JSON sans HTML |
| Paper broker simulé local | ABSENT | Le « paper » = vrais ordres sur compte démo MT5. Acceptable, mais aucun simulateur bid/ask/slippage/rejet pour la recherche |
| Champion/challenger | PARTIELLEMENT FONCTIONNEL | Registre versionné + champion pour LightGBM ; **promotion du champion automatique** à chaque retrain ([trainer.py:121](../apps/engine/app/learning/trainer.py#L121)) — contraire à la gouvernance cible ; pas de shadow mode challenger |
| Détection de dérive | ABSENT | Aucune (features, prédictions, spreads, coûts) |
| Idempotence des ordres | PARTIELLEMENT FONCTIONNEL | 1 entrée/bougie M5 marquée après exécution ; mais pas de `client_order_id` unique ni de garde contre double envoi en cas de retry |
| Réconciliation DB↔broker | FONCTIONNEL | Conservative (jamais de PnL deviné) ; résolution manuelle des références Capital.com héritées |
| Health checks | PARTIELLEMENT FONCTIONNEL | `/health` moteur basique ; pas de vérification horloge/latence/fraîcheur données |
| Tests moteur | PARTIELLEMENT FONCTIONNEL | 13 modules `tests_manual` (assert-based, lancés un par un) ; pas de pytest, pas de CI, pas de couverture risque/exécution complète |

### API (apps/api) — audit détaillé §3.2

| Fonctionnalité | État |
|---|---|
| Proxys dashboard → moteur (15 routes) | FONCTIONNEL mais À SÉCURISER |
| Rapports Telegram quotidien/hebdo/mensuel (crons UTC) | FONCTIONNEL (bugs B2/B5/B6 §3.2) |
| Auth / protection des routes | ABSENT — **5 routes mutantes publiques** dont fermeture de positions broker |
| Validation des entrées (DTO/ValidationPipe) | ABSENT — body proxifié brut vers le moteur |
| CORS | DÉFECTUEUX — `origin: true` + `credentials: true` si `FRONTEND_URL` absent |
| `/health` API | DÉFECTUEUX — HTTP 200 même DB injoignable |
| Analytics (win rate, PF, equity curve) | DÉFECTUEUX — courbe figée après 500 snapshots (`orderBy asc + take 500`) ; agrégats en JS sur toute la table |
| Notifications évènementielles (trade, kill switch, anomalie) | ABSENT |
| Tests API | MOCKÉ — starter « Hello World! » uniquement |

### Web (apps/web) et infra

| Fonctionnalité | État | Détail |
|---|---|---|
| Dashboard Next.js 16 / React 19 — 7 routes (`/`, `/marche`, `/positions`, `/ia`, `/modeles`, `/analytics`, `/parametres`) | FONCTIONNEL | Polling 10-30 s via `use-polling.ts`, lightweight-charts, aucun WebSocket (contrairement au README) |
| Affichage « API injoignable » | PARTIELLEMENT FONCTIONNEL | 5 composants le gèrent (stats, robot-status, system, réconciliation) ; **10 composants sur 15 ignorent `error`** → panne API indistinguable de « aucune donnée » sur `/ia`, `/marche`, `/analytics`, `/modeles` |
| Pages risque / erreurs / backtests / gouvernance (promotion-rollback actifs) | ABSENT | Verrous exposés en lecture seule sur `/modeles` et `/parametres` uniquement |
| Docker (Postgres 16 + Redis 7) | FONCTIONNEL | Redis provisionné mais utilisé nulle part |
| Scripts start/stop + fenêtre 9h-20h jours ouvrés | FONCTIONNEL | `stop-auto.ps1` déclenche les rapports Telegram avant l'arrêt (le cron 21h UTC ne tomberait jamais) ; tâches planifiées **non versionnées** (aucun XML/script d'enregistrement) ; `stop-auto` tue tout process sur 8000/3001/3002 sans vérifier le propriétaire |
| Tests web | PARTIELLEMENT FONCTIONNEL | `lint`, `typecheck`, garde `test:ui-text` ; aucun test unitaire/e2e |
| CI/CD | ABSENT | Aucun workflow (vérifié : pas de `.github/`, gitlab, etc.) |
| Reproductibilité builds Python | DÉFECTUEUX | `requirements.txt` en `>=` sans borne haute ni lockfile |
| Secret scan / lint Python (ruff) / typage Python (mypy) | ABSENT | |

---

## 3. Problèmes détectés

### 3.1 Moteur — problèmes classés par gravité

**P0 — risque de perte non contrôlée ou de décision fausse**

1. **Limite de perte quotidienne inopérante après réalisation** :
   `balance - nav ≥ limite` ([manager.py:50](../apps/engine/app/risk/manager.py#L50))
   ne mesure que le flottant. Une série de pertes *réalisées* remet le compteur
   à zéro (equity ≈ balance) → le bot peut perdre indéfiniment par petites
   clôtures SL. La limite doit être calculée depuis les trades clôturés du jour
   (DB) + flottant.
2. **Aucun filtre d'annonces** : un scalp XAUUSD qui trade pendant NFP/CPI/FOMC
   subit spreads ×10 et slippage massif. La garde de spread aide mais est
   réactive, pas préventive.
3. **Pas de pertes consécutives / limite hebdo / plafond d'exposition** dans le
   RiskManager (le cooldown vit dans la stratégie, contournable par un
   changement de stratégie).
4. **Le tuner adaptatif pilote la taille de position** (`position_size`) :
   l'IA module le risque, borné certes (0.25-1.0 ×), mais la règle cible
   « l'IA ne modifie jamais le risque en production » n'est pas respectée dans
   sa forme actuelle. Le win-rate>65% *augmente* la taille — c'est de
   l'anti-martingale douce mais non gouvernée par le RiskEngine.
5. **Promotion automatique du champion** à chaque retrain LightGBM
   (`make_champion=True`) + hot-swap immédiat de la stratégie live par la
   learning loop — contraire à « promotion manuelle uniquement ». (Atténué :
   `LEARNING_ENABLED=false` par défaut et scalp_m5 ne passe pas par ce chemin.)

**P1 — intégrité / traçabilité**

6. Pas d'idempotence formelle des ordres (`client_order_id`) : un retry réseau
   après timeout MT5 pourrait doubler un ordre.
7. Pas de labels d'apprentissage en production : ni MFE/MAE, ni coûts réels,
   ni premier-niveau-touché ; le tuner apprend sur le PnL net seul, fenêtre 30
   trades — sur-réaction statistique probable (8 trades suffisent à changer
   les paramètres).
8. `uncertainty = 1 - confidence` et confiance scalp = formule ad hoc
   (0.5 + 0.15×votes) : aucune calibration ; les champs `probability_up` etc.
   du signal structuré sont des pseudo-probabilités.
9. Décisions/trades sans versions de config risque, sans snapshot marché lié,
   sans raison de rejet risque persistée en table dédiée (tout est dans
   `features` JSON non typé).
10. Horloge/latence jamais vérifiées ; `MT5_UTC_OFFSET_HOURS` manuel (erreur
    DST silencieuse possible → bougies décalées en base).

**P2 — robustesse / dette**

11. `_macd_hist` recalcul EMA(12/26) sur toute la fenêtre à chaque barre de la
    signal line — approximation d'EMA non stabilisée (valeurs ≠ MACD standard
    sur fenêtre courte) ; RSI/EMA recalculés from scratch à chaque itération.
12. Boucles `while True` sans backoff exponentiel ni compteur d'échecs ; une
    erreur broker répétée toutes les 5 s spamme les logs sans alerte.
13. `tests_manual` non intégrés (pas de runner unique, pas de CI) ; aucun test
    du RiskManager, du filling mode, de la conversion lots, de l'idempotence.
14. Le simulateur de recherche et l'exécution live partagent peu de code : la
    parité exécution/backtest repose sur de la discipline manuelle.
15. Redis provisionné mais inutilisé ; `stop_loss_pct`/`risk_reward_ratio`
    globaux résiduels côté settings alors que la stratégie les fournit.

### 3.2 API — synthèse de l'audit détaillé

**P0**
- Aucune authentification sur 21 routes, dont 5 mutantes :
  `POST /dashboard/reconciliation/run` (peut clôturer côté broker),
  `POST /dashboard/trades/:id/resolve`, `POST /reports/*/run` (écrit en DB,
  spam Telegram). TODO JWT assumé dans le code.
- CORS : `FRONTEND_URL` absent → `origin: true` + `credentials: true`.

**P1**
- Erreurs moteur avalées sans log (`catch { return null }`) et re-livrées en
  HTTP 200 avec données factices (`positions: []` = moteur mort ou zéro
  position, indistinguable) — traitement incohérent selon l'endpoint.
- Aucune validation d'entrée (pas de ValidationPipe/DTO) ; body de
  `resolve` transmis brut au moteur.
- Zéro test métier ; `npm test` n'exécute même pas le e2e starter.

**P2**
- `analytics()` : `orderBy time asc + take 500` → courbe d'équité figée après
  500 snapshots ; agrégats calculés en JS sur toute la table.
- `/health` renvoie 200 même DB down (dangereux pour un orchestrateur).
- Risque de fuite du token Telegram dans les logs d'erreur fetch (URL
  contenant le token dans `cause`).
- Drawdown : convention de signe incohérente quotidien vs hebdo/mensuel ;
  baseline du « P&L du jour » non bornée dans le temps ; course entre crons
  du vendredi 21h.
- Clamp de pagination sans borne basse (`?limit=-500` → `take: -500`).

**P3**
- Duplication fetch moteur ×3 (timeouts 8/10/20 s), fallbacks géants dupliquant
  le contrat FastAPI, `GET /` « Hello World! », modèle `User` + `JWT_SECRET`
  morts, défaut Prisma `instrument = "XAU_USD"` vs données `XAUUSD`, pas
  d'index `Trade.closedAt`, commentaires de schéma périmés (OANDA).

### 3.3 Web / infra — synthèse de l'audit

**P0 / élevé**

- **Le moteur FastAPI expose 23 endpoints sans aucune authentification ni
  CORS**, dont `POST /trade/step`, `/trades/reconcile`, `/learning/retrain`,
  `/ingest/*` ([main.py](../apps/engine/app/main.py)). Atténué par le binding
  local `127.0.0.1` en lancement natif, mais le Dockerfile engine écoute sur
  `0.0.0.0` et le README documente un scénario tunnel/Railway qui rendrait ces
  routes publiques.
- Mêmes routes mutantes non protégées côté API NestJS (cf. §3.2).

**P1**

- 10 composants front sur 15 ignorent l'erreur de polling : une panne API
  s'affiche comme « aucune donnée » (« Aucune décision pour l'instant ») —
  confusion opérationnelle réelle sur un dashboard de trading.
- Aucune CI : lint/typecheck/tests ne tournent que manuellement.
- Dépendances Python non épinglées (`>=` sans lockfile) : build moteur non
  reproductible.
- Tâches planifiées Windows décrites dans le README mais non versionnées
  (aucun export XML ni script `Register-ScheduledTask`).

**P2 / hygiène**

- `FRONTEND_URL=http://localhost:3000` dans `apps/api/.env.example` alors que
  le front tourne sur 3002 (source du faux « API arrêtée » historique) ;
  incohérences de port 3000/3002 répétées dans README et en-tête de
  `start.ps1`.
- `stop-auto.ps1` tue tout process écoutant 8000/3001/3002 sans vérifier le
  propriétaire ; `$ErrorActionPreference='SilentlyContinue'` global dans
  `start-hidden.ps1` masque les vraies erreurs.
- `apps/web/.env.example` non versionné (le `.gitignore` local `.env*` n'a pas
  l'exception `!.env.example`).
- `.vscode/PythonImportHelper-v2-Completion.json` (270 Ko de cache IDE) commité
  par erreur.
- Divergences README↔code : JWT/WebSockets/PyTorch annoncés mais absents ;
  4 pages du dashboard non documentées ; RUNBOOK en anglais et incomplet
  (`/marche` manquant).

**Secrets : audit propre.** Aucun secret réel dans l'arbre ni dans l'historique
git (vérifié par recherche de motifs de tokens et `git log -S`) ; `.env` non
trackés ; seuls des placeholders (`change-me`) et identifiants Docker de dev
locaux sont versionnés.

---

## 4. Écarts majeurs vs architecture cible (refonte)

| Brique cible | État | Décision de migration |
|---|---|---|
| Stratégie LIQUIDITY_SWEEP_TREND_CONTINUATION (H1/M15/M5/M1) | ABSENT | Nouveau package `app/strategy_v2/` (structure, liquidité, sweep, réintégration, retest) branché sur le contrat `Strategy` existant |
| Machine à états explicite | ABSENT | Nouveau module, transitions persistées |
| Filtre fondamental (calendrier éco) | ABSENT | Interface abstraite + provider ; fail-closed si données indisponibles |
| RiskEngine complet (jour/semaine/consécutives/cooldown/kill switch dynamique) | PARTIEL | Refactor de `risk/manager.py` — indépendant de l'IA, config YAML versionnée |
| Kill switch dynamique + réactivation explicite + notification | PARTIEL | Nouveau `risk/kill_switch.py` + endpoints lock/unlock + Telegram |
| Modèles IA (régime, qualité signal, coûts, anomalies) + calibration + incertitude | PARTIEL/ABSENT | Entraînement hors ligne uniquement, registre étendu, promotion manuelle |
| Labels barrière + MFE/MAE + coûts par trade | ABSENT | Nouvelles tables + pipeline post-trade |
| Backtest évènementiel réaliste (bid/ask, spread variable, slippage, latence, rejets) | PARTIEL | Nouveau moteur backtest pour stratégies à règles ; rapports HTML |
| Paper broker simulé | ABSENT | Optionnel — le compte démo MT5 reste le mode paper principal ; simulateur requis pour le backtest/contrefactuel |
| Champion/challenger + shadow + promotion manuelle | PARTIEL | Retirer `make_champion=True` automatique ; statuts RESEARCH→…→CHAMPION |
| Dérive (features, prédictions, coûts) | ABSENT | Fenêtres glissantes vs stats d'entraînement |
| Notifications évènementielles Telegram | ABSENT | Étendre le service existant (kill switch, anomalies, trades) |
| Dashboard : pages risque/erreurs/modèles/backtests | ABSENT | Étendre Next.js (pas de Streamlit) |
| Sécurité API (auth, CORS strict, validation) | ABSENT | Clé d'API locale ou JWT + ValidationPipe + CORS explicite |
| Tests (pytest, unitaires risque/exécution, intégration, sécurité) + CI | ABSENT | pytest + workflow GitHub Actions sans broker réel |

## 5. Ce qui est conservé tel quel (composants stables)

- `broker/mt5.py` (client MT5) — sera durci (idempotence, refus si aucun
  filling mode fiable, vérif horloge) mais pas réécrit.
- Ingestion/backfill/resample et historique Dukascopy/FRED.
- Réconciliation conservative et résolution manuelle.
- Verrous démo multicouches et kill switch statique (étendus, jamais affaiblis).
- Tables Prisma existantes (extension par migrations additives uniquement,
  aucune donnée historique perdue).
- Dashboard Next.js et rapports Telegram (étendus).
- Scripts Windows de fenêtre de fonctionnement.

## 6. Risques immédiats à corriger avant toute nouvelle fonctionnalité

1. Limite de perte quotidienne réelle (DB + flottant) — P0.
2. Auth + CORS strict + validation sur l'API (les routes mutantes sont
   publiques sur le LAN) — P0.
3. Filtre d'annonces fail-closed avant tout élargissement du paper trading — P0.
4. Suppression de la promotion automatique de champion — P0 gouvernance.
5. Idempotence des ordres (client_order_id + garde de retry) — P1.
