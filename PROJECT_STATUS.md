# NexaGold - Etat Phase 0

Date: 2026-07-14

## Validations

- Web: `npm run lint` OK.
- Web: `npm run typecheck` OK.
- API: `npx eslint "{src,apps,libs,test}/**/*.ts"` OK.
- API: `npx tsc --noEmit` OK.
- API: `npm test -- --runInBand` OK, mais tests starter uniquement.
- Engine: tests manuels `test_risk_bracket`, `test_labeling`, `test_registry` OK.

## Etat local observe

- PostgreSQL et Redis Docker ont ete demarres avec `docker compose up -d`.
- API `/health` repond avec `database: ok`.
- Dashboard local repond sur `http://localhost:3002`.
- Le moteur a ete teste puis arrete volontairement.

## Point de securite

Lors du test moteur, `/health` a indique:

- `capital_env: demo`
- `trading_enabled: true`
- `broker_configured: true`
- `ingestion_running: true`

Le moteur a ensuite ete arrete pour ne pas laisser une boucle broker active sans
validation explicite. Avant toute relance longue du moteur, verifier
`apps/engine/.env` et remettre `TRADING_ENABLED=false` si l'objectif est une
observation sans execution d'ordres.

## Prochaine priorite recommandee

La securisation des routes API a ete reportee a la demande utilisateur. La
priorite immediate devient donc l'observabilite operationnelle:

- exposer clairement le kill switch dans le dashboard ;
- afficher l'etat moteur, broker, ingestion et boucle trading ;
- rendre les incoherences visibles avant de modifier le comportement du bot.

## Reconciliation broker

Ajoute:

- confirmation best-effort d'un ordre Capital.com via `GET /confirms/{dealReference}` ;
- stockage du vrai `dealId` quand le broker le renvoie ;
- comparaison read-only DB OPEN trades vs positions broker ouvertes ;
- endpoint moteur `GET /trades/reconciliation` ;
- endpoint moteur `POST /trades/reconcile` qui rattache les IDs broker ;
- option `close_missing=true` pour cloturer un trade DB seulement si
  `history/activity` contient un evenement de fermeture accepte ;
- proxy API `GET /dashboard/reconciliation` ;
- proxy API `POST /dashboard/reconciliation/run` ;
- panneau de reconciliation dans la page Positions ;
- bouton dashboard pour lancer la synchronisation de cloture avec retour visuel.
- resolution manuelle des trades stale depuis le panneau Positions:
  `CANCELLED` sans P&L, ou `CLOSED` avec prix de sortie manuel et P&L calcule.

La cloture automatique reste conservative: sans `dealId` broker ou sans evenement
de fermeture clair, le trade reste `OPEN` et apparait comme anomalie de
reconciliation au lieu de recevoir un P&L estime.

Test live controle:

- moteur lance temporairement avec `TRADING_ENABLED=false`,
  `TRADING_LOOP_ENABLED=false`, `INGEST_ENABLED=false` ;
- `POST /dashboard/reconciliation/run` a repondu OK ;
- resultat observe: 9 trades `OPEN` en DB, 1 position ouverte broker, 1 match,
  8 trades DB absents du broker ;
- aucune cloture automatique: les 8 anciens trades ont des references `o_...`
  sans evenement de fermeture exploitable dans l'historique broker.
- apres resolution manuelle depuis le dashboard: 1 trade DB ouvert, 1 position
  broker ouverte, 1 match et 0 anomalie restante.

## Signal structure

Ajoute:

- contrat de signal structure cote moteur (`symbol`, `timeframe`, `direction`,
  probabilites, confiance, incertitude, qualite donnees, regime, entree/SL/TP,
  raisons, warnings, mode d'execution) ;
- endpoint moteur read-only `GET /signal/latest` ;
- proxy API `GET /dashboard/signal` ;
- panneau `Signal structure` dans le Centre IA ;
- test manuel `tests_manual.test_structured_signal`.

Limite volontaire: la confiance reste le score brut LightGBM et est marquee par
un warning tant que la calibration statistique n'est pas implementee.

## Moteur mathematique XAUUSD

Ajoute:

- module pur `app.signals.math_features` ;
- rendements simple/log/cumule ;
- momentum 3/12 et acceleration ;
- volatilite realisee 20, ratio vol 5/20 ;
- ATR 14 et ATR en pourcentage ;
- z-score 20 ;
- pente de regression 20 et force de tendance ;
- score de qualite des donnees ;
- integration du resume mathematique dans le signal structure ;
- affichage de quelques metriques dans le Centre IA ;
- test manuel `tests_manual.test_math_features`.

## Market Regime Engine v1

Ajoute:

- module pur `app.signals.regime` ;
- classification deterministe `BULLISH_TREND`, `BEARISH_TREND`, `RANGE`,
  `*_HIGH_VOLATILITY`, `LOW_DATA_QUALITY`, `UNKNOWN` ;
- details `trend`, `volatility`, `confidence`, raisons et warnings ;
- integration dans le signal structure (`market_regime`, `regime_details`) ;
- affichage de la confiance de regime dans le Centre IA ;
- test manuel `tests_manual.test_regime`.

Limite volontaire: v1 est une heuristique explicable basee sur momentum, pente,
z-score, vol ratio et qualite des donnees. Elle ne remplace pas encore une
validation statistique par regime.

## Filtre regime/signal read-only

Ajoute:

- verdict structure `regime_gate` (`ALLOWED`, `BLOCKED`, `NOT_APPLICABLE`) ;
- blocage du preview si la qualite effective est inferieure a `0.80` ;
- blocage en volatilite extreme (`vol ratio >= 2.2` ou `ATR/prix >= 2 %`) ;
- blocage d'une contradiction BUY/SELL avec un regime oppose de confiance
  superieure ou egale a `0.45` ;
- avertissements sans blocage pour regime lateral, forte volatilite non extreme
  et compatibilite indeterminee ;
- affichage du verdict et de l'accord modele/regime dans le Centre IA ;
- tests des cas aligne, contradictoire, volatilite extreme, donnees faibles et
  bougies trop anciennes.

Test controle en mode `PAPER`: le modele proposait `BUY` avec un score brut de
`0.9063`, tandis que le regime etait `BEARISH_TREND` avec une confiance de
`0.803`. Le filtre a correctement retourne `NO_TRADE`, `BLOCKED`, `CONFLICT`.
Ce verdict reste limite a `GET /signal/latest` et ne modifie pas encore la boucle
d'execution reelle.
