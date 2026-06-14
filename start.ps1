# ============================================================
#  NexaGold - Lancement de tous les services (PowerShell)
#  Usage : clic droit > Exécuter avec PowerShell, ou : ./start.ps1
#  Dashboard : http://localhost:3000
# ============================================================
$root = $PSScriptRoot
Write-Host "`n ===== Démarrage de NexaGold =====`n"

# 1. Infra Docker (PostgreSQL + Redis)
Write-Host "[1/4] Infra Docker (PostgreSQL + Redis)..."
docker compose -f "$root\docker-compose.yml" up -d 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    Docker Desktop ne répond pas - démarrage..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "    Attente de Docker (40s)..."
    Start-Sleep -Seconds 40
    docker compose -f "$root\docker-compose.yml" up -d
}

# 2. Moteur Python (port 8000)
Write-Host "[2/4] Moteur IA (port 8000)..."
Start-Process cmd -ArgumentList '/k', '.venv\Scripts\uvicorn.exe app.main:app --port 8000' -WorkingDirectory "$root\apps\engine"

# 3. API NestJS (port 3001)
Write-Host "[3/4] API (port 3001)..."
Start-Process cmd -ArgumentList '/k', 'npm run start:dev' -WorkingDirectory "$root\apps\api"

# 4. Frontend Next.js / Dashboard (port 3002 ; 3000 pris par un autre projet local)
Write-Host "[4/4] Dashboard (port 3002)..."
Start-Process cmd -ArgumentList '/k', 'npm run dev -- -p 3002' -WorkingDirectory "$root\apps\web"

Write-Host "`n Ouverture du dashboard dans ~12s..."
Start-Sleep -Seconds 12
Start-Process "http://localhost:3002"

Write-Host "`n ===== NexaGold lancé ====="
Write-Host " Dashboard : http://localhost:3002"
Write-Host " API       : http://localhost:3001/health"
Write-Host " Moteur    : http://localhost:8000/health`n"
