# NexaGoldAI Runbook

## Ports

- Web Next.js: `http://localhost:3002`
- API NestJS: `http://localhost:3001`
- Engine FastAPI: `http://127.0.0.1:8000`

## Safe engine mode

Use this mode for tests and dashboard work:

```powershell
cd D:\Projets\NexaGoldAI\apps\engine
$env:CAPITAL_ENV='demo'
$env:TRADING_ENABLED='false'
$env:TRADING_LOOP_ENABLED='true'
$env:STRATEGY_NAME='expected_return_paper'
$env:MODEL_GRANULARITY='H1'
$env:TRADE_INTERVAL_SECONDS='3600'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Expected health:

- `capital_env: demo`
- `trading_enabled: false`
- `paper_only: true`
- `loop_running: true`

## Start API

```powershell
cd D:\Projets\NexaGoldAI\apps\api
npm run start:dev
```

Check:

```powershell
Invoke-RestMethod http://localhost:3001/dashboard/system
```

## Start web

```powershell
cd D:\Projets\NexaGoldAI\apps\web
npm run dev -- --port 3002
```

Open:

```text
http://localhost:3002
```

## Promotion gate

Official contract:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/paper/promotion-eligibility
Invoke-RestMethod http://localhost:3001/dashboard/promotion-eligibility
```

Live promotion must stay blocked until all requirements pass:

- edge score calibrated as probability
- paper validation complete
- regime filter historically validated
- demo/paper lock reviewed

Automatic live promotion is always disabled.

## Front checks

```powershell
cd D:\Projets\NexaGoldAI\apps\web
npm run typecheck
npm run lint
npm run test:ui-text
```

## Engine checks

```powershell
cd D:\Projets\NexaGoldAI\apps\engine
.\.venv\Scripts\python.exe -m compileall app
```

## Main pages to verify

- `/`
- `/ia`
- `/modeles`
- `/positions`
- `/analytics`
- `/parametres`

Each page should return `200` and show no raw machine status such as `BUY`,
`NO_TRADE`, `missing_on_broker`, or corrupted mojibake text.
