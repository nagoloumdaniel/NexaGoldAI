@echo off
REM ============================================================
REM  NexaGold - Lancement de tous les services (double-clic)
REM  Dashboard : http://localhost:3002
REM  (3002 car le port 3000 est utilise par un autre projet local)
REM ============================================================
cd /d "%~dp0"
title NexaGold - Lanceur

echo.
echo  ===== Demarrage de NexaGold =====
echo.

REM --- 1. Infra (PostgreSQL + Redis via Docker) ---
echo [1/4] Infra Docker (PostgreSQL + Redis)...
docker compose up -d 2>nul
if errorlevel 1 (
  echo     Docker Desktop ne repond pas - tentative de demarrage...
  start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  echo     Attente de Docker ^(40s^)...
  timeout /t 40 /nobreak >nul
  docker compose up -d
)

REM --- 2. Moteur Python (FastAPI) - port 8000 ---
echo [2/4] Moteur IA (port 8000)...
start "NexaGold - Moteur" /d "%~dp0apps\engine" cmd /k ".venv\Scripts\uvicorn.exe app.main:app --port 8000"

REM --- 3. API NestJS - port 3001 ---
echo [3/4] API (port 3001)...
start "NexaGold - API" /d "%~dp0apps\api" cmd /k "npm run start:dev"

REM --- 4. Frontend Next.js (Dashboard) - port 3002 ---
echo [4/4] Dashboard (port 3002)...
start "NexaGold - Dashboard" /d "%~dp0apps\web" cmd /k "npm run dev -- -p 3002"

echo.
echo  Services en cours de demarrage dans des fenetres separees.
echo  Ouverture du dashboard dans ~12s...
timeout /t 12 /nobreak >nul
start http://localhost:3002

echo.
echo  ===== NexaGold lance =====
echo  Dashboard : http://localhost:3002
echo  API       : http://localhost:3001/health
echo  Moteur    : http://localhost:8000/health
echo.
echo  Pour tout arreter : double-cliquez sur stop.bat
echo  ^(Fermer cette fenetre n'arrete PAS les services.^)
echo.
pause
