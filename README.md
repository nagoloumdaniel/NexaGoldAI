# NexaGold

Plateforme de trading algorithmique sur l'or (XAU/USD) pilotée par IA.

## Architecture

```
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
                                      │ OANDA v20   │
                                      │ (démo/réel) │
                                      └─────────────┘
```

| Application | Rôle | Déploiement |
|---|---|---|
| `apps/web` | Dashboard Next.js 16 + Tailwind | Vercel |
| `apps/api` | Backend NestJS + Prisma (utilisateurs, JWT, notifications, WebSockets) | Railway (Dockerfile) |
| `apps/engine` | Moteur de trading Python/FastAPI (OANDA, stratégies, gestion du risque) | Railway (Dockerfile) |
| PostgreSQL | Trades, bougies, décisions IA, équité | Neon |
| Redis | Cache, temps réel | Upstash |

## Décisions techniques (et pourquoi)

- **OANDA** comme broker v1 : API REST pure (aucun terminal à faire tourner,
  contrairement à IBKR/MT5), données temps réel et historiques incluses,
  compte démo identique au compte réel. IBKR envisagé en v2.
- **Dukascopy** pour l'historique profond (backtesting/entraînement) ;
  le flux OANDA pour la décision temps réel.
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
cp .env.example .env                 # renseigner OANDA_API_KEY / OANDA_ACCOUNT_ID
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/health

# 4. Frontend
cd apps/web
npm install
npm run dev                          # http://localhost:3000
```

Pour obtenir les identifiants OANDA : créer un compte démo (fxTrade Practice)
sur oanda.com, puis « Manage API Access » → générer un token. L'ID de compte
est visible dans la liste des comptes (format `101-004-XXXXXXX-001`).

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
   Variables : `OANDA_API_KEY`, `OANDA_ACCOUNT_ID`, `OANDA_ENV=practice`,
   `DATABASE_URL`, `REDIS_URL`, `TRADING_ENABLED=false`.
4. ⚠️ Le moteur doit rester sur une offre **always-on** (jamais de plan qui
   endort les services) : une position ouverte doit toujours être surveillée.

### Vercel (web)
1. Importer le repo sur [vercel.com](https://vercel.com), Root Directory = `apps/web`.
2. Variable : `NEXT_PUBLIC_API_URL` (URL Railway de l'api).

## Feuille de route

1. **Pipeline de données** : ingestion continue OANDA → table `Candle`,
   backfill historique Dukascopy.
2. **Backtesting + premier modèle** : features techniques, LightGBM,
   validation walk-forward (Sharpe, drawdown, profit factor).
3. **Paper trading** : boucle complète données → signal → risque → ordre sur
   compte démo, journalisation de chaque décision (`StrategyDecision`).
4. **Dashboard** : positions, historique, analytics, raisons des décisions IA.
5. **Boucle d'apprentissage** : réentraînement périodique, comparaison de
   stratégies, puis exploration RL (PPO) une fois le pipeline validé.

Le passage en réel (`OANDA_ENV=live`, `TRADING_ENABLED=true`) n'est envisagé
qu'après plusieurs semaines de paper trading aux métriques stables.
