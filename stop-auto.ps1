# ============================================================
#  NexaGold - Arret AUTOMATIQUE (non interactif)
#  Appele par la tache planifiee "NexaGold - Stop 21h".
#  Coupe moteur (8000) + API (3001) + dashboard (3002) + Docker.
#  Pas de "pause" : concu pour tourner sans interaction.
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'
$root    = $PSScriptRoot
$log     = Join-Path $root 'nexagold-scheduler.log'
$pidFile = Join-Path $root 'logs\pids.txt'

function Log($m) {
  "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss')) [STOP] $m" |
    Out-File -FilePath $log -Append -Encoding utf8
}

Log '=== Arret automatique demande ==='

# 1a) Demarrage arriere-plan (start-hidden.ps1) : tuer l'arbre via les PID memorises
if (Test-Path $pidFile) {
  foreach ($procId in (Get-Content $pidFile | Where-Object { $_ -match '^\d+$' })) {
    taskkill /PID $procId /T /F 2>$null | Out-Null
    Log "Arbre du PID $procId arrete"
  }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 1b) Demarrage classique (start.bat) : fermer les fenetres par titre
foreach ($t in @('NexaGold - Moteur', 'NexaGold - API', 'NexaGold - Dashboard', 'NexaGold - Lanceur')) {
  taskkill /FI "WINDOWTITLE eq $t*" /T /F 2>$null | Out-Null
}

# 2) Filet de securite : tuer ce qui ecoute encore sur les ports applicatifs
foreach ($p in 8000, 3001, 3002) {
  $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    try {
      Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop
      Log "Port $p -> PID $($c.OwningProcess) arrete"
    } catch { }
  }
}

# 3) Arreter les conteneurs Docker NexaGold (les donnees Postgres/Redis sont conservees)
Push-Location $root
docker compose stop 2>$null | Out-Null
Pop-Location
Log 'Conteneurs Docker arretes (docker compose stop)'

Log '=== Arret termine ==='
