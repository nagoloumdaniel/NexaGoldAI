# RUNBOOK — exploitation quotidienne

Dernière mise à jour : 2026-07-28. Pour les incidents, voir
[docs/INCIDENT_RESPONSE.md](docs/INCIDENT_RESPONSE.md).

## Ports

- Dashboard Next.js : `http://localhost:3002`
- API NestJS : `http://localhost:3001`
- Moteur FastAPI : `http://127.0.0.1:8000`
- PostgreSQL (Docker) : `5433`

## Broker : MetaTrader 5 (local)

Le moteur pilote le terminal MT5
(`C:\Program Files\MetaTrader 5\terminal64.exe`) via le paquet Python
`MetaTrader5`, **Windows uniquement**. Prérequis :

- MT5 installé avec un compte **démo** (`MT5_LOGIN`, `MT5_PASSWORD`,
  `MT5_SERVER` dans `apps/engine/.env`) ;
- le terminal peut être fermé, le moteur le démarre (`MT5_TERMINAL_PATH`) ;
- `SYMBOL` doit correspondre au symbole or du broker (`XAUUSD`, `XAUUSD.a`…) ;
- `MT5_UTC_OFFSET_HOURS` aligne l'heure serveur MT5 sur UTC (souvent 2 l'hiver,
  3 l'été) — une erreur ici décale toutes les bougies stockées.

Le moteur ne peut plus tourner sous Docker/Linux.

## Démarrage

**Quotidien** : double-clic sur `Demarrer NexaGold (arriere-plan).vbs`, ou
automatiquement par les tâches planifiées (jours ouvrés 9h-20h).
`Arreter NexaGold.vbs` arrête tout.

**Mode moteur sûr** (tests, travail sur le dashboard — aucun ordre possible) :

```powershell
cd D:\Projets\NexaGoldAI\apps\engine
$env:TRADING_ENABLED='false'
$env:TRADING_LOOP_ENABLED='false'
$env:INGEST_ENABLED='false'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**API et dashboard** :

```powershell
cd D:\Projets\NexaGoldAI\apps\api ; npm run start:dev
cd D:\Projets\NexaGoldAI\apps\web ; npm run dev -- --port 3002
```

> En mode production (`npm run start:prod`), l'API sert un build : après
> modification du code, `npm run build` est obligatoire.

## Vérifications rapides

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health              # moteur
Invoke-RestMethod http://127.0.0.1:8000/risk/status         # risque + kill switch
Invoke-RestMethod http://127.0.0.1:8000/fundamental/status  # filtre d'annonces
Invoke-RestMethod http://127.0.0.1:8000/trade/status        # stratégie active
Invoke-RestMethod "http://127.0.0.1:8000/data/quality?granularity=M1&source=db"
Invoke-RestMethod http://localhost:3001/dashboard/system    # vue API
```

État attendu en paper : `broker_env: demo`, `paper_only: true`, kill switch
déverrouillé, `trading_enabled` selon la décision de l'opérateur.

## Contrat de promotion

```powershell
Invoke-RestMethod http://127.0.0.1:8000/paper/promotion-eligibility
```

La promotion live reste **bloquée** tant que toutes les exigences ne sont pas
satisfaites (score calibré, validation paper complète, filtre de régime validé,
verrou démo/paper). La promotion automatique est toujours désactivée.

## Tests et qualité

```powershell
# Moteur
cd D:\Projets\NexaGoldAI\apps\engine
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m compileall -q app

# API
cd D:\Projets\NexaGoldAI\apps\api
npx tsc --noEmit ; npx eslint "{src,apps,libs,test}/**/*.ts" ; npm test -- --runInBand

# Dashboard
cd D:\Projets\NexaGoldAI\apps\web
npm run typecheck ; npm run lint ; npm run test:ui-text
```

## Recherche

```powershell
cd D:\Projets\NexaGoldAI\apps\engine
# Backtest de la stratégie active
.\.venv\Scripts\python.exe -m app.backtesting.run --days 180
# Dataset d'entraînement puis modèle (candidat, jamais promu automatiquement)
.\.venv\Scripts\python.exe -m app.learning.dataset_builder --days 180
.\.venv\Scripts\python.exe -m app.learning.train_signal_quality
```

## Pages à vérifier après une modification du dashboard

`/` · `/marche` · `/positions` · `/ia` · `/modeles` · `/analytics` ·
`/erreurs` · `/risque` · `/parametres`

Chaque page doit répondre `200`, n'afficher aucun statut machine brut (`BUY`,
`NO_TRADE`, `missing_on_broker`) ni caractère corrompu, et distinguer « aucune
donnée » de « API injoignable ».
