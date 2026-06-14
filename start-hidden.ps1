# ============================================================
#  NexaGold - Demarrage en ARRIERE-PLAN (aucune fenetre)
#  Lance moteur (8000) + API (3001) + dashboard (3002) sans
#  terminal visible. Les sorties vont dans .\logs\*.log.
#  Les PID lances sont notes dans .\logs\pids.txt pour un
#  arret propre (kill de l'arbre) par stop-auto.ps1.
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'
$root     = $PSScriptRoot
$logDir   = Join-Path $root 'logs'
$pidFile  = Join-Path $logDir 'pids.txt'
$schedLog = Join-Path $root 'nexagold-scheduler.log'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Log($m) {
  "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss')) [START] $m" |
    Out-File -FilePath $schedLog -Append -Encoding utf8
}
function Test-Port($p) {
  [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

# Lance une commande dans un cmd masque ; sortie -> fichier log ; renvoie le PID du cmd parent.
function Start-Hidden($name, $workdir, $cmdline, $port) {
  if (Test-Port $port) { Log "$name deja actif (port $port) - ignore"; return $null }
  $log = Join-Path $logDir "$name.log"
  $proc = Start-Process -FilePath 'cmd.exe' `
    -ArgumentList '/c', "$cmdline > `"$log`" 2>&1" `
    -WorkingDirectory $workdir -WindowStyle Hidden -PassThru
  Log "$name lance (port $port, pid $($proc.Id), log: $log)"
  return $proc.Id
}

Log '=== Demarrage en arriere-plan demande ==='

# 1) Infra Docker (Postgres + Redis) - pas de fenetre
Push-Location $root
docker compose up -d 2>$null | Out-Null
Pop-Location
Log 'Docker compose up -d'

# 2/3/4) Services applicatifs en arriere-plan
$pids = @()
$pids += Start-Hidden 'engine' (Join-Path $root 'apps\engine') '.venv\Scripts\uvicorn.exe app.main:app --port 8000' 8000
$pids += Start-Hidden 'api'    (Join-Path $root 'apps\api')    'npm run start:dev' 3001
$pids += Start-Hidden 'web'    (Join-Path $root 'apps\web')    'npm run dev -- -p 3002' 3002

# Memorise les PID parents pour un arret propre (kill de l'arbre)
$pids | Where-Object { $_ } | Out-File -FilePath $pidFile -Encoding utf8
Log "=== Services lances en arriere-plan (pids: $($pids -join ', ')) ==="

Write-Host "NexaGold demarre en arriere-plan. Dashboard : http://localhost:3002"
Write-Host "Logs : $logDir   |   Arret : stop-auto.ps1"
