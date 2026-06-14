# NexaGold

Plateforme de trading algorithmique sur l'or (XAU/USD) pilotée par IA.

## Architecture

```text
                    ┌─────────────────────┐
                    │  apps/web (Next.js) │  ← Vercel
                    │  Tableau de bord    │
                    └─────────┬───────────┘
                              │ HTTPS / WebSocket
                    ┌─────────▼───────────┐
                    │  apps/api (NestJS)  │  ← Railway
                    │  Utilisateurs, JWT, │
                    │  notifications      │
                    └────┬───────────┬────┘
                         │           │
        ┌────────────────▼──┐   ┌────▼────────────────────┐
        │ Neon (PostgreSQL) │   │ apps/engine (FastAPI)   │  ← Railway
        │ Upstash (Redis)   │   │ Données → Stratégie →   │
        └───────────────────┘   │ Risque → Exécution      │
                                └────────────┬────────────┘
                                             │ REST
                                      ┌──────▼──────┐
                                      │ Capital.com │
                                      │ (démo/réel) │
                                      └─────────────┘
```

| Application | Rôle | Déploiement |
| --- | --- | --- |
| `apps/web` | Dashboard Next.js 16 + Tailwind | Vercel |
| `apps/api` | Backend NestJS + Prisma (utilisateurs, JWT, notifications, WebSockets) | Railway (Dockerfile) |
| `apps/engine` | Moteur de trading Python/FastAPI (Capital.com, stratégies, gestion du risque) | Railway (Dockerfile) |
| PostgreSQL | Trades, bougies, décisions IA, équité | Neon |
| Redis | Cache, temps réel | Upstash |

## Décisions techniques (et pourquoi)

- **Capital.com** comme broker v1 : API REST pure (aucun terminal à faire
  tourner, contrairement à IBKR/MT5), authentification par clé API, prix en
  streaming, compte démo identique au compte réel. IBKR envisagé en v2.
- **Dukascopy** pour l'historique profond (backtesting/entraînement) ;
  le flux Capital.com pour la décision temps réel.
- **PostgreSQL standard** (pas TimescaleDB) : Neon ne supporte pas
  l'extension, et le volume M1 (~370 000 bougies/an) reste trivial pour
  Postgres avec la clé composite de `Candle`.
- **PyTorch + LightGBM** côté IA (pas TensorFlow) : on démarre par du
  gradient boosting mesurable, le deep learning/RL viendra après validation
  du pipeline de backtesting.
- **`TRADING_ENABLED=false` par défaut** : le moteur ne peut pas envoyer
  d'ordre tant que le kill switch n'est pas explicitement levé.

## Démarrage local

Prérequis : Node 22+, Python 3.12+, Docker Desktop.

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
cp .env.example .env                 # renseigner les identifiants Capital.com
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/health

# 4. Frontend
cd apps/web
npm install
npm run dev                          # http://localhost:3000
```

Pour obtenir les identifiants Capital.com : sur votre compte, **activez la
2FA** (obligatoire pour l'API), basculez en mode **Démo**, puis Paramètres →
**API integrations** → **Generate API Key**. Capital.com demande un mot de
passe personnalisé pour la clé (distinct du mot de passe du compte). Vous
obtenez trois éléments : `CAPITAL_API_KEY` (la clé), `CAPITAL_IDENTIFIER`
(l'e-mail de connexion) et `CAPITAL_PASSWORD` (le mot de passe de la clé).

## Déploiement

### Neon (PostgreSQL)

1. Créer un projet sur [neon.tech](https://neon.tech), copier la connection string.
2. Appliquer le schéma : `DATABASE_URL=<neon-url> npx prisma migrate deploy` depuis `apps/api`.

### Upstash (Redis)

1. Créer une base sur [upstash.com](https://upstash.com), copier l'URL `rediss://`.

### Railway (api + engine)

1. Créer un projet Railway relié à ce repo GitHub.
2. Service **api** : Root Directory = `apps/api` (le Dockerfile est détecté).
   Variables : `DATABASE_URL` (Neon), `REDIS_URL` (Upstash), `FRONTEND_URL`
   (URL Vercel), `JWT_SECRET`.
3. Service **engine** : Root Directory = `apps/engine`.
   Variables : `CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER`, `CAPITAL_PASSWORD`,
   `CAPITAL_ENV=demo`, `EPIC=GOLD`, `DATABASE_URL`, `REDIS_URL`,
   `TRADING_ENABLED=false`.
4. ⚠️ Le moteur doit rester sur une offre **always-on** (jamais de plan qui
   endort les services) : une position ouverte doit toujours être surveillée.

### Vercel (web)

1. Importer le repo sur [vercel.com](https://vercel.com), Root Directory = `apps/web`.
2. Variable : `NEXT_PUBLIC_API_URL` (URL Railway de l'api).

## Notifications Telegram (rapport quotidien)

L'api envoie chaque jour de semaine à 21h00 UTC (configurable via
`REPORT_CRON`) un rapport sur Telegram : P&L du jour, solde, équité,
drawdown, trades clôturés. Un `EquitySnapshot` est enregistré à chaque
rapport — c'est aussi lui qui alimente la courbe d'équité du dashboard.

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

Test sans attendre le cron :

```bash
curl -X POST http://localhost:3001/reports/daily/run
```

Le rapport nécessite que le moteur (`ENGINE_URL`) soit démarré avec des
identifiants Capital.com valides — c'est lui qui fournit solde et équité.

## Pipeline de données (phase 1)

Le moteur ingère les bougies de l'or de Capital.com dans la table `Candle`
(écriture directe via asyncpg, en partageant `DATABASE_URL` avec l'api). La
clé composite `(instrument, granularity, time)` rend l'ingestion idempotente.

- **Ingestion continue** : une boucle de fond rafraîchit les dernières bougies
  de chaque granularité toutes les `INGEST_INTERVAL_SECONDS`. Démarre
  automatiquement si la base est joignable et Capital.com configuré.
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
# backfill court depuis Capital.com (granularité + nb de jours, max 60)
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
- **Capital.com** (boucle continue + `/ingest/backfill`) : le **temps réel** et
  les bougies récentes (Dukascopy publie avec un délai).

Les deux écrivent dans la même série `(GOLD, granularité, time)` : là où elles
se recouvrent, la dernière écriture gagne. Les prix concordent (OHLC mid) ;
seule la sémantique du **volume** diffère (Capital.com = volume négocié,
Dukascopy = nombre de ticks). Sans impact pour un backtesting basé sur le prix.
Usage recommandé : Dukascopy pour amorcer l'historique, puis la boucle
Capital.com pour entretenir le présent.

## Backtesting & modèle (phase 2)

Module de recherche dans [apps/engine/app/research/](apps/engine/app/research/) :
`features.py` (indicateurs techniques causaux), `labeling.py` (cible 3 classes
hausse/baisse/consolidation sur le rendement futur), `backtest.py` (validation
walk-forward LightGBM + backtest PnL), `run.py` (CLI).

```bash
cd apps/engine
.venv\Scripts\python.exe -m app.research.run --granularity M5 --horizon 12 --threshold 0.001 --folds 5
```

Le CLI charge les bougies depuis la base, évalue le modèle en **walk-forward**
(chaque barre de test n'est prédite que par un modèle entraîné sur des barres
strictement antérieures — pas de fuite de données), puis simule un backtest
long/short avec coûts de transaction. Il écrit `models/<granularité>/` :
`model.joblib` (modèle final), `meta.json`, `report.json`. Métriques produites :
accuracy, F1 macro, matrice de confusion, et côté PnL Sharpe annualisé, max
drawdown, profit factor, win rate, exposition.

[lightgbm_strategy.py](apps/engine/app/strategy/lightgbm_strategy.py) charge ce
modèle et implémente l'interface `Strategy` — c'est le pont vers le paper
trading (phase 3).

> **Résultat du premier modèle (baseline, à ne PAS trader).** Sur 30 jours de
> M5, accuracy ≈ 34 % (≈ hasard sur 3 classes) et, après coûts, la stratégie
> perd. C'est le résultat attendu d'un modèle naïf sur peu de données — et
> précisément ce que le backtesting sert à révéler **avant** de risquer du
> capital. L'infrastructure (évaluation sans fuite, métriques, sauvegarde,
> pont stratégie) est en place ; trouver un edge réel = itérer sur features,
> labelling et volume de données.

## Feuille de route

1. ✅ **Pipeline de données** : ingestion continue Capital.com → table `Candle`,
   backfill historique Dukascopy. *(fait)*
2. ✅ **Backtesting + premier modèle** : features techniques, LightGBM,
   validation walk-forward (Sharpe, drawdown, profit factor). *(infrastructure
   faite ; le baseline n'a pas d'edge, à itérer)*
3. **Paper trading** : boucle complète données → signal → risque → ordre sur
   compte démo, journalisation de chaque décision (`StrategyDecision`).
4. **Dashboard** : positions, historique, analytics, raisons des décisions IA.
5. **Boucle d'apprentissage** : réentraînement périodique, comparaison de
   stratégies, puis exploration RL (PPO) une fois le pipeline validé.

Le passage en réel (`CAPITAL_ENV=live`, `TRADING_ENABLED=true`) n'est envisagé
qu'après plusieurs semaines de paper trading aux métriques stables.
