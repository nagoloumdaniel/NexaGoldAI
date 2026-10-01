# NexaGold

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![NestJS](https://img.shields.io/badge/NestJS-11-E0234E?logo=nestjs&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)
![Prisma](https://img.shields.io/badge/Prisma-7-2D3748?logo=prisma&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![MetaTrader 5](https://img.shields.io/badge/MetaTrader_5-Windows_only-0C8CE9)
![License: none](https://img.shields.io/badge/license-non%20spécifiée-lightgrey)

Système de trading algorithmique sur l'or (XAU/USD), piloté par un moteur Python relié au terminal MetaTrader 5, avec API NestJS et dashboard Next.js.

## Description

NexaGold est un monorepo composé d'un moteur de décision Python/FastAPI, d'une API NestJS/Prisma et d'un dashboard Next.js. Le moteur ingère les bougies de l'or depuis MetaTrader 5 et Dukascopy, applique une stratégie de trading à base de règles (analyse multi-timeframe M15/M30/H1, entrée M5), et journalise chaque décision avant de l'exécuter.

Le projet est davantage un **cadre de validation et de gestion du risque** qu'un système de trading prêt pour le réel : kill switch (`TRADING_ENABLED=false` par défaut), verrou de compte démo vérifié auprès du terminal, limites de risque par trade et par jour, embargo anti-fuite de données dans le backtesting walk-forward, et un historique de décisions (`PROJECT_STATUS.md`) qui documente des stratégies rejetées faute d'edge net plutôt qu'un chemin linéaire vers la mise en production.

## Fonctionnalités clés

- **Ingestion de données** : boucle continue depuis MetaTrader 5 (temps réel) et backfill historique depuis Dukascopy (ticks → bougies), écriture idempotente dans PostgreSQL.
- **Stratégie scalp multi-timeframe** (`scalp_m5`) : votes de tendance EMA/RSI/MACD sur M15/M30/H1, déclencheur d'entrée sur M5, clôture dès profit net atteint, stop ATR côté serveur du broker.
- **Gestion du risque** : taille de position bornée par `MAX_RISK_PER_TRADE_PCT`, nombre de positions simultanées plafonné (`MAX_OPEN_POSITIONS`), filtre de spread, zones RSI interdites, cooldown après perte.
- **Tuner adaptatif borné** : ajustement automatique des paramètres de la stratégie scalp après chaque trade clôturé, avec journal des changements (raison, avant/après).
- **Backtesting walk-forward** : LightGBM + validation par plis avec embargo temporel, deux méthodes de labelling (seuil fixe, triple barrière), métriques Sharpe/drawdown/profit factor.
- **Boucle d'apprentissage** : réentraînement périodique, comparaison de configurations candidates, registre de modèles versionné avec promotion automatique du meilleur (champion/challenger).
- **Dashboard de suivi** : solde, équité, drawdown, graphique chandelier (TradingView Lightweight Charts), flux des décisions IA avec leurs raisons, historique des trades.
- **Notifications Telegram** : récapitulatifs quotidien, hebdomadaire et mensuel envoyés automatiquement par l'API.
- **Double verrou démo/réel** : chaque stratégie paper refuse de se charger si `BROKER_ENV=live`, même avec le kill switch levé.

## Stack technique

| Composant | Technologies |
| --- | --- |
| Moteur de trading | Python, FastAPI, pandas, scikit-learn, LightGBM, paquet `MetaTrader5` |
| API backend | NestJS 11, Prisma 7, PostgreSQL |
| Dashboard | Next.js 16, React 19, Tailwind CSS 4, TradingView Lightweight Charts |
| Infrastructure locale | Docker Compose (PostgreSQL + Redis) |
| Infrastructure visée en déploiement | Neon (PostgreSQL), Upstash (Redis), Railway (API), Vercel (dashboard) |

## Démo

Il n'y a pas de démo publique. Le moteur de trading dépend du terminal **MetaTrader 5 installé localement sous Windows** et ne peut pas tourner dans un conteneur Docker ou sur Railway (le paquet Python `MetaTrader5` est Windows-only). Seule l'API et le dashboard sont déployables séparément ; sans le moteur en local, les panneaux « live » du dashboard restent vides.

## Installation et lancement local

Prérequis : Node.js 22+, Python 3.12+, Docker Desktop, **MetaTrader 5 installé** (`C:\Program Files\MetaTrader 5\terminal64.exe`) avec un **compte démo**.

```bash
# 1. Base de données et Redis locaux
docker compose up -d

# 2. Backend NestJS
cd apps/api
cp .env.example .env
npm install
npx prisma migrate dev --name init
npm run start:dev                    # http://localhost:3001

# 3. Moteur Python
cd apps/engine
cp .env.example .env                 # renseigner les identifiants MT5 (démo)
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000   # http://localhost:8000

# 4. Dashboard
cd apps/web
npm install
npm run dev                          # http://localhost:3000
```

Variables d'environnement principales (voir `.env.example` dans chaque app) :

- `apps/engine/.env` : `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_TERMINAL_PATH`, `SYMBOL`, `DATABASE_URL`, `TRADING_ENABLED` (kill switch, `false` par défaut).
- `apps/api/.env` : `DATABASE_URL`, `REDIS_URL`, `FRONTEND_URL`, `ENGINE_URL`, `JWT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- `apps/web` : `NEXT_PUBLIC_API_URL`.

## Structure du projet

```text
apps/
├── engine/   # Moteur Python/FastAPI : ingestion, stratégie, risque, exécution MT5
├── api/      # API NestJS + Prisma : utilisateurs, dashboard, rapports Telegram
└── web/      # Dashboard Next.js (TypeScript, Tailwind CSS)
docker-compose.yml   # PostgreSQL + Redis pour le développement local
```

## Avertissement

**Projet en développement, exécuté uniquement en compte démo (paper trading).** Le kill switch `TRADING_ENABLED` est désactivé par défaut et chaque stratégie vérifie que le compte MetaTrader 5 connecté est un compte démo avant d'envoyer un ordre. Le passage en argent réel n'est pas automatisé et n'est pas prévu avant une validation paper prospective stable sur plusieurs semaines — voir `PROJECT_STATUS.md` pour l'historique des validations et des stratégies rejetées faute d'edge net démontré.

---

[GitHub @nagoloumdaniel](https://github.com/nagoloumdaniel) · [Portfolio](https://nagoloum.vercel.app)
