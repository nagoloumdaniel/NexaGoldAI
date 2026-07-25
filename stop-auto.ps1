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

# 0) Envoyer le rapport Telegram AVANT de couper quoi que ce soit.
#    A 21h locale (UTC+2) le bot s'eteint 2h AVANT le cron rapport (21h UTC),
#    donc le cron ne se declenche jamais : on le declenche ici, pendant que
#    l'API (3001) et le moteur (8000) sont encore vivants.
$apiUrl = 'http://localhost:3001'
function Send-Report($path, $label) {
  try {
    Invoke-RestMethod -Uri "$apiUrl/$path" -Method Post -TimeoutSec 30 | Out-Null
    Log "Rapport $label envoye ($path)"
  } catch {
    Log "Echec rapport $label : $($_.Exception.Message)"
  }
}
$now = [DateTime]::Now
if ($now.DayOfWeek -ne [DayOfWeek]::Saturday -and $now.DayOfWeek -ne [DayOfWeek]::Sunday) {
  Send-Report 'reports/daily/run' 'quotidien'
}
if ($now.DayOfWeek -eq [DayOfWeek]::Friday) { Send-Report 'reports/weekly/run' 'hebdo' }
if ($now.AddDays(1).Month -ne $now.Month) { Send-Report 'reports/monthly/run' 'mensuel' }

# 1a) Demarrage arriere-plan (start-hidden.ps1) : tuer l'arbre via les PID memorises
if (Test-Path $pidFile) {
  foreach ($procId in (Get-Content $pidFile | Where-Object { $_ -match '^\d+$' })) {
    taskkill /PID $procId /T /F 2>$null | Out-Null
    Log "Arbre du PID $procId arrete"
  }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 1b) Demarrage classique (start.ps1, fenetres visibles) : fermer par titre
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

# NB: le terminal MetaTrader 5 (terminal64.exe) n'est PAS arrete ici, et c'est
# voulu : les SL/TP des positions sont stockes cote serveur du broker (ils
# restent actifs meme terminal ferme), mais laisser MT5 ouvert preserve les
# graphiques/l'usage manuel. Pour le couper aussi, decommenter :
# taskkill /IM terminal64.exe /F 2>$null | Out-Null

# 3) Arreter les conteneurs Docker NexaGold (les donnees Postgres/Redis sont conservees)
Push-Location $root
docker compose stop 2>$null | Out-Null
Pop-Location
Log 'Conteneurs Docker arretes (docker compose stop)'

Log '=== Arret termine ==='
