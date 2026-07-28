# NexaGold

Plateforme de trading algorithmique sur l'or (XAU/USD) pilotée par IA.

## Architecture

```text
                    ┌─────────────────────┐
                    │  apps/web (Next.js) │  ← port 3002
                    │  Tableau de bord    │
                    └─────────┬───────────┘
                              │ HTTP (polling 10-30 s)
                    ┌─────────▼───────────┐
                    │  apps/api (NestJS)  │  ← port 3001
                    │  Proxy dashboard,   │
                    │  rapports, alertes  │
                    └────┬───────────┬────┘
                         │           │
        ┌────────────────▼──┐   ┌────▼────────────────────┐
        │ PostgreSQL        │   │ apps/engine (FastAPI)   │  ← PC Windows local
        │ (Docker local)    │   │ Données → Stratégie →   │     port 8000
        └───────────────────┘   │ Risque → Exécution      │
                     ▲          └────────────┬────────────┘
                     └───── SystemEvent ─────┤ IPC (paquet MetaTrader5)
                            (relais alertes) │
                                ┌────────────▼────────────┐
                                │ Terminal MetaTrader 5   │
                                │ C:\Program Files\...    │
                                │ (compte démo)           │
                                └─────────────────────────┘
```

| Application | Rôle | Déploiement |
| --- | --- | --- |
| `apps/web` | Dashboard Next.js 16 + Tailwind (port 3002) | Local (Vercel possible) |
| `apps/api` | Backend NestJS + Prisma : proxy dashboard, rapports Telegram, relais d'alertes (port 3001) | Local (Railway possible) |
| `apps/engine` | Moteur de trading Python/FastAPI (MetaTrader 5, stratégies, risque, backtest, IA) | **Windows local uniquement** (terminal MT5 requis) |
| PostgreSQL | Trades, bougies, décisions, résultats post-trade, journaux | Docker local (port 5433) |
| Redis | Provisionné par docker-compose, **non utilisé** à ce jour | Docker local (port 6380) |

> **Authentification** : il n'y a pas de comptes utilisateurs ni de JWT. Les
> routes mutantes sont protégées par une clé d'API partagée (`API_KEY` côté
> NestJS, `ENGINE_API_TOKEN` côté moteur) et les services écoutent sur
> `127.0.0.1` par défaut. Voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

| Document | Contenu |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Composants, flux d'une décision, persistance, sécurité, verrous |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Stratégies disponibles, pipeline sweep, paramètres, validation |
| [docs/RISK_MANAGEMENT.md](docs/RISK_MANAGEMENT.md) | Limites, dimensionnement, kill switch, procédures |
| [docs/BACKTESTING.md](docs/BACKTESTING.md) | Moteur évènementiel, coûts simulés, limites connues |
| [docs/AI_MODELS.md](docs/AI_MODELS.md) | Pipeline IA, labels, verdicts (v1 rejetée) |
| [docs/INCIDENT_RESPONSE.md](docs/INCIDENT_RESPONSE.md) | Que faire quand ça casse |
| [docs/AUDIT_BOT_TRADING.md](docs/AUDIT_BOT_TRADING.md) | Audit complet du dépôt (2026-07-27) |
| [docs/ROADMAP_AI_TRADING.md](docs/ROADMAP_AI_TRADING.md) | Plan de refonte, phase par phase |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Changements notables |
| [RUNBOOK.md](RUNBOOK.md) | Exploitation quotidienne |

## Décisions techniques (et pourquoi)

- **MetaTrader 5** comme broker (remplace Capital.com depuis 2026-07) : le
  moteur pilote le terminal MT5 installé localement
  (`C:\Program Files\MetaTrader 5`) via le paquet Python `MetaTrader5` (pont
  IPC). Conséquences assumées : **Windows uniquement**, le terminal doit
  tourner, et le moteur n'est plus déployable sur Railway/Docker — il reste
  sur le PC local, ce qui colle au fonctionnement réel (jours ouvrés,
  9h-20h). Avantages : compte démo gratuit chez n'importe quel broker MT5,
  SL/TP stockés côté serveur du broker, exécution standard de l'industrie.
- **Stratégie scalp multi-timeframe** (depuis 2026-07-26, remplace la
  régression expected-return H1 en live) : analyse de tendance sur M15/M30/H1,
  entrée sur M5 uniquement, BUY et SELL, **clôture dès que la position est en
  profit net** (voir « Paper trading »). Les paramètres sensibles sont ajustés
  automatiquement par un tuner adaptatif borné qui apprend des trades clôturés.
- **Dukascopy** pour l'historique profond (backtesting/entraînement) ;
  le flux MetaTrader 5 pour la décision temps réel.
- **PostgreSQL standard** (pas TimescaleDB) : Neon ne supporte pas
  l'extension, et le volume M1 (~370 000 bougies/an) reste trivial pour
  Postgres avec la clé composite de `Candle`.
- **LightGBM et scikit-learn** côté IA (ni PyTorch ni TensorFlow à ce
  jour) : on démarre par des modèles mesurables et interprétables ; le deep
  learning ne se justifiera qu'après avoir démontré un edge sur des modèles
  simples. Voir [docs/AI_MODELS.md](docs/AI_MODELS.md) — le premier modèle de
  qualité de signal a été **rejeté** (aucun pouvoir prédictif).
- **`TRADING_ENABLED=false` par défaut** : le moteur ne peut pas envoyer
  d'ordre tant que le kill switch n'est pas explicitement levé.

## Démarrage local

### Lancement rapide (double-clic, sans terminal)

Après la première installation (ci-dessous), tout se relance en **double-cliquant
`Demarrer NexaGold (arriere-plan).vbs`** à la racine : il démarre l'infra Docker
puis les 3 services **en arrière-plan, sans aucune fenêtre**, avec les sorties
redirigées vers `logs\*.log`. `Arreter NexaGold.vbs` arrête tout.

- **Dashboard : <http://localhost:3002>** (port 3002 car 3000 est utilisé par un
  autre projet local ; pinné dans le lanceur).
- API : `localhost:3001` · Moteur : `localhost:8000`.

Sous le capot, les `.vbs` appellent `start-hidden.ps1` / `stop-auto.ps1`. Trois
tâches planifiées Windows automatisent le cycle — **fenêtre de fonctionnement :
jours ouvrés (lun-ven), 9h-20h locale** :

- `NexaGold - Start (allumage)` — à chaque ouverture de session (délai 1 min).
  Le script (appelé avec `-AutoScheduled`) ne démarre les services **que si on
  est un jour ouvré entre 9h et 20h** ; sinon il journalise le refus et
  n'allume rien. Il attend le daemon Docker (jusqu'à 4 min), lance le terminal
  MT5 si besoin, puis les 3 services. Idempotent : un service actif est ignoré.
- `NexaGold - Start 09h` — lun-ven à 9h00, si le PC est resté allumé.
- `NexaGold - Stop 20h` — tous les jours à 20h00 : rapports Telegram envoyés
  puis arrêt des services (filet de sécurité même le week-end).

Le double-clic **manuel** sur `Demarrer NexaGold (arriere-plan).vbs` reste
possible à toute heure (le garde-fou ne s'applique qu'aux lancements
automatiques). Prérequis : l'installation initiale doit avoir été faite une
fois (Docker démarré, `npm install`, venv + `pip install`, `prisma migrate`).

### Installation initiale (une fois)

Prérequis : Node 22+, Python 3.12+, Docker Desktop, **MetaTrader 5 installé**
(`C:\Program Files\MetaTrader 5\terminal64.exe`) avec un **compte démo**.

```bash
# 1. Base de données et Redis locaux
docker compose up -d

# 2. Backend NestJS
cd apps/api
cp .env.example .env
npm install
npx prisma migrate dev --name init   # crée les tables
npm run start:dev                    # http://localhost:3001/health

# 3. Moteur Python
cd apps/engine
cp .env.example .env                 # renseigner les identifiants MT5 (démo)
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/health

# 4. Frontend
cd apps/web
npm install
npm run dev -- --port 3002           # http://localhost:3002
```

Pour obtenir les identifiants MetaTrader 5 (compte démo) : ouvrez le terminal
MT5 → **Fichier → Ouvrir un compte** → choisissez un broker (ou le serveur
d'essai MetaQuotes-Demo) → type **Démo**. À la création, MT5 affiche trois
éléments à reporter dans `apps/engine/.env` : `MT5_LOGIN` (numéro de compte),
`MT5_PASSWORD` (mot de passe principal) et `MT5_SERVER` (nom du serveur, ex.
`MetaQuotes-Demo`). Vérifiez aussi dans le Market Watch le nom exact du
symbole or chez ce broker (`XAUUSD`, `XAUUSD.a`, `GOLD`…) → `SYMBOL`, et le
décalage horaire du serveur → `MT5_UTC_OFFSET_HOURS` (heure des bougies MT5
moins heure UTC ; souvent 2 l'hiver, 3 l'été). Le moteur lance le terminal
tout seul s'il est fermé (`MT5_TERMINAL_PATH`).

### Amorcer les données et le modèle (une fois, après le 1er démarrage)

Le moteur tourne « à vide » tant qu'il n'a pas de données ni de modèle. Avec le
moteur démarré (port 8000) :

```bash
cd apps/engine
# 1. Historique profond de l'or (≈ 30-40 min pour 1 an ; ajuster --days)
.venv\Scripts\python.exe -m app.data.backfill_cli --granularity M5 --days 365
# 2. (optionnel) proxy macro EUR/USD, même période
.venv\Scripts\python.exe -m app.data.backfill_cli --granularity M5 --days 365 \
    --symbol EURUSD --divisor 100000 --instrument EURUSD
# 3. (optionnel, recherche) bougies H1 dérivées des M5
curl -X POST "http://localhost:8000/candles/resample?source=M5&target=H1&instrument=XAUUSD"
# 4. (optionnel, recherche) entraîner l'artefact expected-return paper
.venv\Scripts\python.exe -m app.research.train_expected_return_paper
```

La stratégie live `scalp_m5` est **basée sur des règles** (pas de modèle à
entraîner) : elle lit les bougies M5/M15/M30/H1 directement depuis MT5. Le
backfill ci-dessus ne sert qu'au backtesting/à la recherche. Les étapes 3-4
ne concernent que l'ancienne stratégie expected-return conservée en recherche.

> **Migration Capital.com → MT5** : les bougies historiques sont désormais
> stockées sous la clé instrument `XAUUSD` (= `SYMBOL`). Si votre base date de
> l'époque Capital.com, re-keyez l'ancienne série `GOLD` une fois :
> `docker exec -it nexagoldai-postgres-1 psql -U nexagold -c "UPDATE \"Candle\" SET instrument='XAUUSD' WHERE instrument='GOLD';"`

Ensuite, le moteur ingère le temps réel et décide à chaque minute (une seule
entrée exécutée par bougie M5). La stratégie `scalp_m5` est verrouillée sur
`BROKER_ENV=demo` **et** vérifie auprès du terminal que le compte MT5 connecté
est bien un compte démo. Le dashboard (`localhost:3002`) et les récaps Telegram
reflètent le tout.

> **Granularité d'entrée** : `MODEL_GRANULARITY=M5` (la stratégie scalp trade
> sur M5 ; l'analyse M15/M30/H1 est récupérée automatiquement). Les artefacts
> de recherche restent rangés par granularité (`models/<granularité>/`).

## Déploiement

### Neon (PostgreSQL)

1. Créer un projet sur [neon.tech](https://neon.tech), copier la connection string.
2. Appliquer le schéma : `DATABASE_URL=<neon-url> npx prisma migrate deploy` depuis `apps/api`.

### Upstash (Redis)

1. Créer une base sur [upstash.com](https://upstash.com), copier l'URL `rediss://`.

### Railway (api uniquement)

1. Créer un projet Railway relié à ce repo GitHub.
2. Service **api** : Root Directory = `apps/api` (le Dockerfile est détecté).
   Variables : `DATABASE_URL`, `FRONTEND_URL` (URL Vercel), `API_KEY`
   (obligatoire dès que l'API sort du réseau local), `ENGINE_API_TOKEN`,
   `ENGINE_URL` (URL joignable du moteur local, par ex. via un tunnel, sinon
   les panneaux « live » resteront vides), `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`.

   ⚠️ Exposer l'API hors du poste local **impose** de définir `API_KEY` : sans
   elle, les routes mutantes (réconciliation, résolution de trade, rapports)
   sont ouvertes. Le moteur doit rester injoignable publiquement.

### Moteur (Windows local, non déployable)

⚠️ Depuis la migration MetaTrader 5, le moteur **ne peut plus être déployé sur
Railway/Docker** : le paquet `MetaTrader5` est Windows-only et dialogue avec le
terminal MT5 installé sur ce PC. Le moteur tourne donc en local (`start.ps1` /
tâches planifiées, jours ouvrés 9h-20h). Le Dockerfile de `apps/engine` ne sert plus qu'à un
mode API/lecture seule sans broker. Pendant les heures d'arrêt du bot, les
SL/TP restent actifs car ils sont stockés **côté serveur du broker MT5**.

### Vercel (web)

1. Importer le repo sur [vercel.com](https://vercel.com), Root Directory = `apps/web`.
2. Variable : `NEXT_PUBLIC_API_URL` (URL Railway de l'api).

## Notifications Telegram (récaps automatiques)

L'api envoie sur Telegram, sans intervention :

- **Récap quotidien** — chaque soir à 21h00 UTC (configurable via `REPORT_CRON`) :
  P&L du jour, solde, équité, drawdown, trades clôturés. Un `EquitySnapshot` est
  enregistré à chaque récap (il alimente aussi la courbe d'équité du dashboard).
- **Récap hebdomadaire** — chaque vendredi à 21h00 UTC (en plus du quotidien) :
  performance de la semaine, drawdown max, taux de réussite, P&L réalisé.
- **Récap mensuel** — le dernier jour du mois à 21h00 UTC : même synthèse sur le mois.

Déclenchement manuel pour tester : `POST /reports/daily/run`,
`/reports/weekly/run`, `/reports/monthly/run`.

Configuration (5 minutes) :

1. Sur Telegram, parler à **@BotFather** → `/newbot` → choisir un nom et un
   identifiant. BotFather donne le **token** → `TELEGRAM_BOT_TOKEN`.
2. Envoyer n'importe quel message à votre nouveau bot (obligatoire : un bot
   ne peut pas écrire en premier).
3. Récupérer votre chat id : ouvrir
   `https://api.telegram.org/bot<TOKEN>/getUpdates` dans un navigateur et
   lire `result[0].message.chat.id` → `TELEGRAM_CHAT_ID`.
4. Renseigner les deux variables dans `apps/api/.env` (local) et sur le
   service Railway **api** (production).

Les récaps nécessitent que le moteur (`ENGINE_URL`) soit démarré avec des
identifiants MT5 valides — c'est lui qui fournit solde et équité.

## Pipeline de données (phase 1)

Le moteur ingère les bougies de l'or depuis MetaTrader 5 dans la table `Candle`
(écriture directe via asyncpg, en partageant `DATABASE_URL` avec l'api). La
clé composite `(instrument, granularity, time)` rend l'ingestion idempotente.

- **Ingestion continue** : une boucle de fond rafraîchit les dernières bougies
  de chaque granularité toutes les `INGEST_INTERVAL_SECONDS`. Démarre
  automatiquement si la base est joignable et MT5 configuré.
- **Backfill historique** : remonte le temps par fenêtres de 900 bougies pour
  amorcer le backtesting.

Variables (toutes optionnelles, valeurs par défaut indiquées) :

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `INGEST_ENABLED` | `true` | active la boucle de fond |
| `INGEST_GRANULARITIES` | `M1,M5,M15` | granularités ingérées |
| `INGEST_INTERVAL_SECONDS` | `60` | période du rafraîchissement |
| `INGEST_RECENT_COUNT` | `50` | bougies rafraîchies à chaque tick |

Endpoints (moteur, port 8000) :

```bash
# état du pipeline (base connectée, boucle active)
curl http://localhost:8000/health
# refresh immédiat des dernières bougies
curl -X POST http://localhost:8000/ingest/run
# backfill court depuis MT5 (granularité + nb de jours, max 60)
curl -X POST "http://localhost:8000/ingest/backfill?granularity=M5&days=2"
# backfill profond depuis Dukascopy (ticks → bougies ; M1/M5/M15/M30/H1)
curl -X POST "http://localhost:8000/ingest/dukascopy?granularity=M5&days=3"
# couverture par granularité (count + plage temporelle)
curl http://localhost:8000/candles/stats
```

### Deux sources, une seule série

- **Dukascopy** (`/ingest/dukascopy`) : source de l'**historique profond** pour
  le backtesting. Télécharge les fichiers tick `.bi5` (un par heure, LZMA) en
  pur stdlib, les agrège en bougies. Symbole `XAUUSD`, prix ÷ 1000.
- **MetaTrader 5** (boucle continue + `/ingest/backfill`) : le **temps réel** et
  les bougies récentes (Dukascopy publie avec un délai).

Les deux écrivent dans la même série `(XAUUSD, granularité, time)` : là où
elles se recouvrent, la dernière écriture gagne. Les prix concordent (OHLC) ;
la sémantique du **volume** diffère (MT5 = tick volume, Dukascopy = nombre de
ticks — proches en pratique). ⚠️ MT5 horodate en **heure serveur du broker**,
pas en UTC : réglez `MT5_UTC_OFFSET_HOURS` (souvent 2 l'hiver, 3 l'été) pour
que les bougies MT5 s'alignent sur l'historique Dukascopy (UTC), sinon les
features dépendantes de l'heure seront décalées. Usage recommandé : Dukascopy
pour amorcer l'historique, puis la boucle MT5 pour entretenir le présent.

## Backtesting & modèle (phase 2)

Module de recherche dans [apps/engine/app/research/](apps/engine/app/research/) :
`features.py` (indicateurs techniques causaux), `labeling.py` (cible 3 classes),
`backtest.py` (validation walk-forward LightGBM + backtest PnL), `run.py` (CLI).

Deux méthodes de labelling :

- **fixed** : UP/DOWN si le rendement futur dépasse ±seuil.
- **triple_barrier** : barrières haute/basse à ±`vol_mult` × volatilité récente,
  plus une barrière temporelle ; le label est la première barrière touchée
  (high/low intrabar). Volatilité-adaptatif et sensible au chemin.

```bash
cd apps/engine
.venv\Scripts\python.exe -m app.research.run --granularity M5 \
    --labeling triple_barrier --horizon 24 --vol-mult 1.5 --folds 5
```

Le CLI charge les bougies depuis la base, évalue le modèle en **walk-forward**
(chaque barre de test n'est prédite que par un modèle entraîné sur des barres
strictement antérieures — pas de fuite de données), puis simule un backtest
long/short avec coûts de transaction. Il écrit `models/<granularité>/` :
`model.joblib` (modèle final), `meta.json`, `report.json`. Métriques produites :
accuracy, F1 macro, matrice de confusion, et côté PnL Sharpe annualisé, max
drawdown, profit factor, win rate, exposition.

[expected_return_strategy.py](apps/engine/app/strategy/expected_return_strategy.py)
charge l'artefact séparé `models/H1/expected_return_paper`. Il prédit directement
le rendement à 24 h, ne prend que les achats au-dessus du seuil validé et cible
15 % de volatilité annualisée sans levier. *Depuis 2026-07-26 cette stratégie
n'est plus celle du live (remplacée par `scalp_m5`) ; elle reste disponible en
recherche et réactivable par config.*

### Filtre de confiance, validation séparée, macro

- **Filtre de confiance** : `backtest.run` balaie des seuils et ne prend
  position que si la probabilité du modèle dépasse le seuil. Choisi sur une
  **slice de validation** puis évalué sur une **slice de test held-out** (pas de
  fuite). Un **embargo** (purge) sépare train et test pour empêcher les labels
  futurs de fuiter. Le seuil retenu est sauvegardé en `meta.json` et appliqué en
  live par `LightGBMStrategy` (en dessous → HOLD).
- **Features macro** : EUR/USD (proxy inverse du dollar) aligné sur l'or —
  rendements, volatilité, corrélation glissante. Activées par config ; le Trader
  récupère la macro en direct (sinon HOLD par sécurité). *Mesuré : EUR/USD seul
  n'apporte pas d'edge clair — un vrai signal macro demanderait taux réels/DXY/
  sentiment.*
- **Granularité** : le système entraîne par granularité ; H1 donne le meilleur
  ratio signal/coût.

> **Évolution du modèle.** Validation H1 walk-forward imbriquée :
>
> | Étape | Sharpe |
> | --- | --- |
> | Baseline phase 2 (M5, 30 j, 20 features, fixe) | ≈ −34 |
> | + 1 an de données + ~30 features | ≈ −17 |
> | + filtre de confiance | ≈ −3 |
> | Classification H1 actuelle | −2,03 (rejetée) |
> | Régression 24 h long-only + vol target | 1,19 |
> | **+ bracket max(0,5 %, 3×ATR), objectif 3R** | **1,49** |
>
> Le candidat final affiche +53,33 %, Sharpe 1,49, profit factor 1,25 et max
> drawdown −14,35 % sur 14 665 observations OOS. Un pli récent reste négatif et
> le stress de coûts sévère n'est positif que de +0,66 % : ces chiffres autorisent
> uniquement une validation paper prospective, jamais une conclusion de gain.

## Paper trading (phase 3)

La stratégie live est `scalp_m5`
([scalp_mtf.py](apps/engine/app/strategy/scalp_mtf.py)) : **analyse sur
M15/M30/H1, entrée sur M5 uniquement, sortie au premier profit net**. Deux
boucles tournent en parallèle dans [trader.py](apps/engine/app/execution/trader.py) :

**Boucle de signal** (`TRADE_INTERVAL_SECONDS=60`) :

1. réconcilie les sorties SL/TP, ferme les positions déjà en profit, puis
   calcule les votes de tendance M15/M30/H1 (EMA20/50, RSI14, MACD) — il faut
   au moins `min_votes` timeframes alignés **sans contradiction** ;
2. cherche le déclencheur sur M5 (EMA9/21 dans le sens de la tendance, RSI7,
   bougie de confirmation, RSI14 hors zone d'épuisement) — BUY comme SELL,
   une seule entrée exécutée par bougie M5 ;
3. **journalise chaque décision** dans `StrategyDecision` (exécutée ou non) ;
4. calcule le stop `max(plancher, ATR14 M5 × multiplicateur)` (TP de secours
   `2R` — la sortie normale est la prise de profit anticipée) et la taille via
   le RiskManager : `MAX_RISK_PER_TRADE_PCT=1 %` du solde, borné par la
   distance de stop, modulé par la taille apprise du tuner ;
5. n'envoie un ordre que si le risque approuve (dont
   `MAX_OPEN_POSITIONS=3` — seules les positions du bot, symbole + magic,
   comptent), `TRADING_ENABLED=true`, `BROKER_ENV=demo`, le compte MT5
   connecté est bien un compte **démo**, et le spread reste sous
   `MAX_SPREAD_PCT`.

**Moniteur de prise de profit** (`PROFIT_CHECK_INTERVAL_SECONDS=5`) : vérifie
le P&L net (profit + swap, devise du compte) de chaque position du bot ; dès
qu'il atteint `PROFIT_CLOSE_MIN_NET`, la position est fermée **même si le SL/TP
n'est pas atteint**, et le bot repart chercher un signal. Ce seuil est le
coussin anti-latence/slippage : sans lui, un gain marginal pourrait devenir
négatif le temps que l'ordre de clôture arrive au serveur. Le SL ATR reste posé
côté serveur comme protection (il survit à l'arrêt du bot).

```bash
curl http://localhost:8000/trade/status          # stratégie, kill switch, moniteur profit
curl -X POST http://localhost:8000/trade/step    # une itération immédiate
curl "http://localhost:8000/decisions/recent?limit=20"
curl http://localhost:8000/learning/adaptive     # paramètres appris + ajustements
```

Variables (valeurs actives dans `apps/engine/.env`) : `STRATEGY_NAME=scalp_m5`,
`MODEL_GRANULARITY=M5`, `TRADE_INTERVAL_SECONDS=60`,
`INGEST_GRANULARITIES=M5,M15,M30,H1`, `MAX_OPEN_POSITIONS=3`,
`PROFIT_CHECK_INTERVAL_SECONDS=5`, `PROFIT_CLOSE_MIN_NET=0.5`,
`SCALP_ADAPT_ENABLED=true`, et le kill switch `TRADING_ENABLED`
(défaut code : `false`).

Le statut prospectif est disponible via `GET /paper/validation` et
`GET /dashboard/paper-validation` (suit la stratégie active). La revue devient
éligible après 100 trades clôturés, sans promotion automatique. `scalp_m5`
refuse de charger si `BROKER_ENV=live`, même lorsque `TRADING_ENABLED=true`.

Gardes d'exécution supplémentaires (défauts sûrs) :

- `MAX_SPREAD_PCT=0.001` — aucun ordre si le spread relatif dépasse 0,1 %
  (rollover, annonces, faible liquidité) ;
- zones RSI interdites (pas d'achat suracheté / de vente survendue) et
  **cooldown après perte** (quelques bougies M5, durée apprise) ;
- `REGIME_FILTER_ENFORCED=false` — le filtre de régime reste journalisé en
  shadow (il ne s'applique qu'aux signaux expected-return) ;
- l'ancienne stratégie `expected_return_paper` reste disponible via
  `STRATEGY_NAME=expected_return_paper` + `MODEL_GRANULARITY=H1` (mêmes
  verrous démo ; gate d'espérance nette, SELL désactivé par défaut).

## Dashboard (phase 4)

L'API NestJS expose les données au frontend (module
[dashboard](apps/api/src/dashboard/)) : lecture de la base via Prisma (bougies,
décisions, trades, équité) et proxy du moteur pour le compte/positions en
direct.

```bash
curl http://localhost:3001/dashboard/summary    # compte, drawdown, compteurs
curl "http://localhost:3001/dashboard/candles?granularity=M5&limit=300"
curl "http://localhost:3001/dashboard/decisions?limit=50"
curl http://localhost:3001/dashboard/trades
curl http://localhost:3001/dashboard/analytics  # win rate, profit factor, équité
```

Le dashboard Next.js ([apps/web](apps/web/src/)) consomme ces endpoints
par polling (10 à 30 s selon les panneaux). Sept pages :

| Page | Contenu |
| --- | --- |
| `/` | Cartes de stats (solde, NAV, P&L, drawdown), courbe d'équité, décisions et trades récents |
| `/marche` | Graphique chandelier (Lightweight Charts) et statistiques de marché |
| `/positions` | Positions ouvertes, historique, réconciliation broker et résolution manuelle |
| `/ia` | Signal structuré (probabilités, régime, verdict) et décisions détaillées |
| `/modeles` | Registre des versions, champion actif, validation paper, verrous de promotion |
| `/analytics` | Win rate, profit factor, courbe d'équité, historique complet |
| `/erreurs` | Répartition des décisions (bonne/mauvaise × résultat), causes, MFE/MAE, analyses post-trade |
| `/risque` | Kill switch, consommation des limites, filtre d'annonces, journal des blocages, événements système |
| `/parametres` | État du système (moteur, base, boucles) |

Variables : `NEXT_PUBLIC_API_URL` (URL de l'API), `NEXT_PUBLIC_API_KEY`
(clé des routes mutantes, si `API_KEY` est défini côté NestJS).

```bash
cd apps/web
npm run dev -- --port 3002   # (API sur 3001 + moteur sur 8000 requis)
```

## Boucle d'apprentissage (phase 5)

Le moteur sait se réentraîner et choisir le meilleur modèle tout seul
([apps/engine/app/learning/](apps/engine/app/learning/)). À chaque round,
plusieurs **configurations candidates** (horizons / seuils de labelling
différents) sont évaluées en walk-forward sur les **données les plus récentes** ;
la meilleure (par Sharpe out-of-sample) est entraînée sur tout l'historique,
enregistrée comme nouvelle **version** et promue **champion**. Les configs
moins bonnes sont laissées de côté — « comparer, renforcer la meilleure,
abandonner les moins efficaces ».

- **Registre versionné** ([registry.py](apps/engine/app/learning/registry.py)) :
  `models/<granularité>/registry.json` + un dossier par version
  (`model.joblib`, `meta.json`, `report.json`).
- **Hot-swap** : quand un nouveau champion est promu, la stratégie de la boucle
  de trading est rechargée à chaud, sans redémarrage.
- **Réentraînement périodique** : boucle de fond optionnelle
  (`LEARNING_ENABLED`, défaut **false** car l'entraînement est lourd ;
  `LEARNING_INTERVAL_SECONDS`, défaut quotidien).

```bash
curl -X POST http://localhost:8000/learning/retrain   # un round, renvoie le classement
curl http://localhost:8000/learning/registry          # champion + versions
curl http://localhost:8000/learning/adaptive          # tuner adaptatif scalp
```

### Tuner adaptatif de la stratégie scalp

En plus du réentraînement LightGBM (qui ne concerne pas `scalp_m5`), la
stratégie scalp embarque son propre apprentissage autonome
([adaptive.py](apps/engine/app/learning/adaptive.py)) : après chaque trade
clôturé (prise de profit, SL, TP), le tuner met à jour ses statistiques et,
tous les 8 trades, ré-évalue ses paramètres **dans des bornes dures** :

- trop de pertes (win rate < 45 %) → alignement 3/3 exigé, taille réduite,
  cooldown allongé, zones RSI resserrées ;
- prises de profit qui finissent ≤ 0 (slippage) → coussin `profit_close_min_net`
  relevé ;
- pertes trop lourdes face aux gains → stop ATR resserré ;
- bonne période (win rate > 65 %) → relâchement prudent.

Chaque ajustement est journalisé (raison, avant/après, horodatage) et l'état
est persisté dans `models/scalp_m5/adaptive_state.json` (gitignoré) — le bot
reprend son apprentissage après un redémarrage. Introspection :
`GET /learning/adaptive`. Désactivable via `SCALP_ADAPT_ENABLED=false`.

Le dashboard affiche le panneau **« Modèles & apprentissage »** (champion +
historique des versions avec Sharpe et accuracy), via `/dashboard/models`.

> Exemple réel (1 an de M5, 5 approches) : le système a promu
> `fixed, horizon=24, seuil=0.002` (Sharpe −17,3) — meilleur PnL que les
> variantes triple-barrier, qui pourtant atteignent une accuracy supérieure
> (~50 %). La sélection par Sharpe privilégie donc le PnL net, pas la seule
> précision de classification. Sans edge net, le « meilleur » reste perdant.

## Feuille de route

1. ✅ **Pipeline de données** : ingestion continue MetaTrader 5 → table
   `Candle`, backfill historique Dukascopy. *(fait)*
2. ✅ **Backtesting + premier modèle** : features techniques, LightGBM,
   validation walk-forward (Sharpe, drawdown, profit factor). *(infrastructure
   faite ; le baseline n'a pas d'edge, à itérer)*
3. ✅ **Paper trading** : boucle complète données → signal → risque → ordre sur
   compte démo, journalisation de chaque décision (`StrategyDecision`). *(fait,
   kill switch actif)*
4. ✅ **Dashboard** : positions, historique, analytics, raisons des décisions
   IA, graphique chandelier. *(fait)*
5. ✅ **Boucle d'apprentissage** : réentraînement périodique, comparaison de
   configurations (champion/challenger), promotion automatique. *(fait ;
   exploration RL/PPO en option future)*
6. ✅ **Mode scalp M5** (2026-07-26) : analyse M15/M30/H1, entrée M5, BUY/SELL,
   clôture au premier profit net, 3 positions max, tuner adaptatif borné.
   *(fait ; validation paper prospective en cours)*

Le passage en réel (`BROKER_ENV=live` + compte MT5 réel) n'est envisagé
qu'après plusieurs semaines de paper trading aux métriques stables. Rappel
important : le backtest 2023-2026 à coûts réalistes n'a montré **aucun edge
net** pour la stratégie expected-return, et la stratégie scalp M5 n'a **pas
encore été backtestée** — le mode démo sert à mesurer honnêtement, pas à
préparer un passage en réel imminent.
