# RÉPONSE AUX INCIDENTS

Dernière mise à jour : 2026-07-28.

Réflexe commun à tous les incidents : **d'abord bloquer, ensuite comprendre,
enfin déverrouiller avec une raison écrite.** Un déverrouillage sans diagnostic
est la seule erreur vraiment coûteuse.

## Arrêt d'urgence

```bash
# Bloquer les nouvelles ouvertures (les clôtures restent permises)
curl -X POST -H "x-api-key: $API_KEY" \
  "http://127.0.0.1:8000/risk/lock?reason=Intervention%20operateur"

# Tout arrêter (services + Docker ; le terminal MT5 reste ouvert)
powershell -File stop-auto.ps1
```

Le terminal MT5 est délibérément laissé ouvert : les SL/TP sont stockés côté
serveur du broker et restent actifs même bot éteint.

## Kill switch verrouillé (alerte Telegram reçue)

1. Lire la cause : `GET /risk/status` ou page `/risque`.
2. Vérifier ce qui l'a déclenché : `GET /risk/decisions`, page `/erreurs`.
3. Distinguer **limite légitime atteinte** (le système a fait son travail —
   analyser les trades avant de reprendre) de **fausse alerte** (données
   corrompues, statistiques erronées).
4. Ne déverrouiller qu'après correction :
   `POST /risk/unlock?reason=...` (raison obligatoire, historisée).

## Broker dégradé / déconnecté

Alerte `BROKER_DEGRADED` après 5 échecs consécutifs. Vérifier : terminal MT5
ouvert et connecté, compte non expiré, marché ouvert (week-end ?), symbole
visible dans le Market Watch. Le moteur reprend seul et émet
`BROKER_RECOVERED` — aucune action requise si la panne était transitoire.

## Positions du bot et du broker divergentes

```bash
curl "http://127.0.0.1:8000/trades/reconciliation"      # lecture seule
curl -X POST -H "x-api-key: $API_KEY" \
  "http://127.0.0.1:8000/trades/reconcile?close_missing=true"
```

La réconciliation ne clôture un trade que si l'historique broker prouve la
clôture. Sans preuve, le trade reste ouvert et remonte comme anomalie : c'est
volontaire, on ne fabrique pas de P&L. Résolution manuelle possible depuis la
page `/positions`.

## Données suspectes

```bash
curl "http://127.0.0.1:8000/data/quality?granularity=M1&source=broker"
curl "http://127.0.0.1:8000/data/quality?granularity=M1&source=db"
```

Score < 0.80 : ne pas faire confiance aux décisions prises pendant cette
période. Causes fréquentes : trous d'ingestion, terminal déconnecté,
`MT5_UTC_OFFSET_HOURS` incorrect après un changement d'heure (les bougies
seraient décalées en base).

## Dashboard vide ou « API injoignable »

Ordre de vérification : moteur (`:8000/health`) → API (`:3001/health`) →
PostgreSQL (`docker compose ps`) → `FRONTEND_URL` de l'API inclut bien
`http://localhost:3002`. Rappel : en mode production, l'API sert un build —
après modification du code, `npm run build` est nécessaire.

## Alertes Telegram absentes

`TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` définis côté API, API démarrée (le
relais tourne chaque minute), événements de moins de 3 heures (au-delà ils sont
marqués sans envoi). Vérifier les `SystemEvent` non notifiés en base.

## Après tout incident

1. La cause est-elle visible dans le journal (`/risk/decisions`,
   `/system/events`) ? Si non, ajouter la trace manquante.
2. Un test aurait-il pu l'attraper ? Si oui, l'écrire.
3. Consigner dans `PROJECT_STATUS.md` si le comportement du système change.
