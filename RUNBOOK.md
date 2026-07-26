# NexaGoldAI Runbook

## Ports

- Web Next.js: `http://localhost:3002`
- API NestJS: `http://localhost:3001`
- Engine FastAPI: `http://127.0.0.1:8000`

## Broker: MetaTrader 5 (local)

The engine drives the local MT5 terminal
(`C:\Program Files\MetaTrader 5\terminal64.exe`) through the Windows-only
`MetaTrader5` Python package. Requirements:

- MT5 installed with a **demo** account (`MT5_LOGIN`, `MT5_PASSWORD`,
  `MT5_SERVER` in `apps/engine/.env`);
- the terminal may be closed — the engine starts it via `MT5_TERMINAL_PATH`;
- `SYMBOL` must match the broker's gold symbol (`XAUUSD`, `XAUUSD.a`, ...);
- `MT5_UTC_OFFSET_HOURS` aligns MT5 server time with UTC (usually 2 in
  winter, 3 in summer).

The engine cannot run in Docker/Linux anymore (Windows-only IPC bridge).

## Safe engine mode

Use this mode for tests and dashboard work:

```powershell
cd D:\Projets\NexaGoldAI\apps\engine
$env:BROKER_ENV='demo'
$env:TRADING_ENABLED='false'
$env:TRADING_LOOP_ENABLED='true'
$env:STRATEGY_NAME='scalp_m5'
$env:MODEL_GRANULARITY='M5'
$env:TRADE_INTERVAL_SECONDS='60'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Expected health:

- `broker_env: demo`
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
