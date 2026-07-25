# ============================================================
#  NexaGold - Lancement de tous les services (PowerShell)
#  Usage : clic droit > Exécuter avec PowerShell, ou : ./start.ps1
#  Dashboard : http://localhost:3000
# ============================================================
$root = $PSScriptRoot
Write-Host "`n ===== Démarrage de NexaGold =====`n"

# 1. Infra Docker (PostgreSQL + Redis)
Write-Host "[1/5] Infra Docker (PostgreSQL + Redis)..."
docker compose -f "$root\docker-compose.yml" up -d 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    Docker Desktop ne répond pas - démarrage..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "    Attente de Docker (40s)..."
    Start-Sleep -Seconds 40
    docker compose -f "$root\docker-compose.yml" up -d
}

# 2. Terminal MetaTrader 5 (requis par le moteur : pont IPC local)
Write-Host "[2/5] Terminal MetaTrader 5..."
$mt5Path = 'C:\Program Files\MetaTrader 5\terminal64.exe'
if (-not (Get-Process -Name 'terminal64' -ErrorAction SilentlyContinue)) {
    if (Test-Path $mt5Path) {
        Start-Process $mt5Path
        Write-Host "    MT5 lancé - connexion du moteur dans quelques secondes"
    } else {
        Write-Host "    ATTENTION : $mt5Path introuvable - le moteur le lancera lui-même via MT5_TERMINAL_PATH"
    }
}

# 3. Moteur Python (port 8000)
Write-Host "[3/5] Moteur IA (port 8000)..."
Start-Process cmd -ArgumentList '/k', '.venv\Scripts\uvicorn.exe app.main:app --port 8000' -WorkingDirectory "$root\apps\engine"

# 4. API NestJS (port 3001)
Write-Host "[4/5] API (port 3001)..."
Start-Process cmd -ArgumentList '/k', 'npm run start:dev' -WorkingDirectory "$root\apps\api"

# 5. Frontend Next.js / Dashboard (port 3002 ; 3000 pris par un autre projet local)
Write-Host "[5/5] Dashboard (port 3002)..."
Start-Process cmd -ArgumentList '/k', 'npm run dev -- -p 3002' -WorkingDirectory "$root\apps\web"

Write-Host "`n Ouverture du dashboard dans ~12s..."
Start-Sleep -Seconds 12
Start-Process "http://localhost:3002"

Write-Host "`n ===== NexaGold lancé ====="
Write-Host " Dashboard : http://localhost:3002"
Write-Host " API       : http://localhost:3001/health"
Write-Host " Moteur    : http://localhost:8000/health`n"
