@echo off
REM ============================================================
REM  NexaGold - Arret de tous les services
REM ============================================================
cd /d "%~dp0"
title NexaGold - Arret

echo.
echo  ===== Arret de NexaGold =====
echo.

REM Ferme les fenetres des services (par leur titre)
echo Arret du moteur, de l'API et du dashboard...
taskkill /FI "WINDOWTITLE eq NexaGold - Moteur*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq NexaGold - API*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq NexaGold - Dashboard*" /T /F >nul 2>&1

REM Arrete les conteneurs Docker (laisse les donnees intactes)
echo Arret des conteneurs Docker (les donnees sont conservees)...
docker compose stop 2>nul

echo.
echo  ===== NexaGold arrete =====
echo.
pause
