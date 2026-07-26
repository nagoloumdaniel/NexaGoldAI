# NexaGold - Etat

## Strategie scalp M5 multi-timeframe (clôture au premier profit)

Date: 2026-07-26

La strategie live `expected_return_paper` (H1, horizon 24 h) a ete remplacee
par `scalp_m5`, une strategie a regles demandee par l'operateur :

- **analyse** sur M15/M30/H1 (votes de tendance EMA20/50 + RSI14 + MACD par
  timeframe, alignement `min_votes` sans contradiction requis) ; **entree sur
  M5 uniquement** (EMA9/21, RSI7, bougie de confirmation, zone RSI14
  d'epuisement interdite), BUY et SELL, une entree executee max par bougie M5 ;
- **sortie au premier profit net** : un moniteur dedie verifie toutes les
  `PROFIT_CHECK_INTERVAL_SECONDS` (5 s) le P&L net (profit + swap) des
  positions du bot et ferme des que `PROFIT_CLOSE_MIN_NET` (0.5, coussin
  latence + slippage) est atteint, meme si SL/TP n'est pas touche ; le SL ATR
  (`max(plancher, ATR14 M5 x mult)`) reste pose cote serveur, TP de secours 2R ;
- **3 positions simultanees max** (`MAX_OPEN_POSITIONS=3`), lot calcule par le
  RiskManager (1 % du solde, borne par la distance de stop, module par le
  tuner) ; boucle de signal a `TRADE_INTERVAL_SECONDS=60` ;
  `INGEST_GRANULARITIES=M5,M15,M30,H1` ;
- **tuner adaptatif** (`app/learning/adaptive.py`, etat persiste dans
  `models/scalp_m5/adaptive_state.json`, gitignore) : apres chaque trade
  clos, stats mises a jour ; tous les 8 trades, ajustement borne de
  min_votes / stop ATR / zones RSI / cooldown apres perte / coussin de profit /
  taille — chaque changement journalise avec sa raison ; introspection
  `GET /learning/adaptive` ; desactivable par `SCALP_ADAPT_ENABLED=false` ;
- verrous inchanges : `paper_only`, demo obligatoire (factory + verification
  du compte aupres du terminal), promotion live toujours verrouillee ;
- rapports quotidien/hebdo/mensuel inchanges (crons NestJS + declenchement par
  `stop-auto.ps1` a 20h).

Bugs corriges au passage :

- `MAX_OPEN_POSITIONS` comptait toutes les positions du terminal (une position
  manuelle ou d'un autre symbole bloquait le bot) : le quota ne compte plus que
  les positions du bot (symbole + magic 20260725), via
  `get_open_positions(symbol, magic)` ;
- dashboard : `INSTRUMENT='GOLD'` fige dans `dashboard.service.ts` alors que
  le moteur ecrit `XAUUSD` depuis la migration MT5 — le graphique bougies
  etait vide ; corrige (`INSTRUMENT_KEY` surchargable, defaut `XAUUSD`) ;
- `GET /paper/validation` suivait `expected-return-paper` en dur : suit
  desormais la strategie active ;
- la limite « une entree par bougie M5 » est marquee a l'execution de l'ordre
  (pas dans `evaluate()`), sinon un preview dashboard consommait le signal.

Validation : `tests_manual.test_scalp_mtf` (10 tests strategie + tuner),
`test_risk_bracket`, `test_structured_signal`, compilation Python et
`tsc --noEmit` API OK. Aucun backtest de cette strategie scalp n'a ete
realise : validation paper prospective uniquement.

## Migration broker : Capital.com -> MetaTrader 5

Date: 2026-07-25

Le broker Capital.com a ete entierement remplace par le terminal MetaTrader 5
installe localement (`C:\Program Files\MetaTrader 5`), pilote via le paquet
Python `MetaTrader5` (pont IPC synchrone, encapsule en async).

- nouveau client `app/broker/mt5.py` (`MT5Client`, erreurs `BrokerError`) aux
  memes formes normalisees que l'ancien client : la strategie et le risque
  n'ont pas change de convention ;
- config : `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` / `MT5_TERMINAL_PATH` /
  `MT5_UTC_OFFSET_HOURS` remplacent `CAPITAL_*` ; `EPIC=GOLD` devient
  `SYMBOL=XAUUSD` ; `CAPITAL_ENV` devient `BROKER_ENV` ;
- conversion unites <-> lots a la frontiere broker (contract size, arrondi au
  pas de lot, minimum broker) ; les unites reellement executees sont
  journalisees ;
- plus de guaranteed stop (inexistant sur MT5) : SL/TP standards, stockes
  cote serveur du broker (ils survivent a l'arret du bot 21h-7h) ;
- reconciliation via `history_deals_get` par position (une requete, plus de
  pagination par jour) ; les anciennes references Capital.com `o_...`
  ne sont plus resolubles et passent par la resolution manuelle ;
- gardes ajoutees : spread max (`MAX_SPREAD_PCT`), verification que le compte
  MT5 connecte est bien un compte demo avant tout ordre d'une strategie
  paper, gate d'esperance nette de couts dans la strategie expected-return,
  filtre de regime applicable par `REGIME_FILTER_ENFORCED`, cote SELL
  optionnel (`EXPECTED_RETURN_ALLOW_SHORT`, off par defaut) ;
- le moteur n'est plus deployable sur Railway/Docker (paquet Windows-only) :
  il tourne nativement sur ce PC ; le Dockerfile engine ne sert plus qu'en
  mode API sans broker ;
- scripts `start.ps1` / `start-hidden.ps1` : lancement automatique du
  terminal MT5 ; `stop-auto.ps1` ne tue pas le terminal (SL/TP serveur) ;
- donnees : les bougies sont desormais stockees sous `XAUUSD` ; l'ancienne
  serie `GOLD` doit etre re-keyee une fois (SQL dans le README) ; attention a
  `MT5_UTC_OFFSET_HOURS` pour rester aligne avec l'historique Dukascopy (UTC).

Les entrees ci-dessous sont anterieures a la migration et mentionnent encore
Capital.com : elles restent valables comme historique.

## Etat Phase 0 (historique)

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

## Validation historique du filtre de regime

Ajoute:

- variables historiques causales identiques au filtre live, exclues des features
  LightGBM pour isoler l'effet du filtre ;
- masque de position optionnel dans le simulateur P&L ;
- comparaison au meme seuil de confiance, puis avec seuil filtre choisi sur la
  validation uniquement ;
- decomposition des blocages par regime, accord et raison ;
- metriques d'esperance par barre active et decision conservative de promotion ;
- CLI read-only `python -m app.research.validate_regime --granularity H1` ;
- test manuel `tests_manual.test_regime_backtest`.

Validation H1 walk-forward, 5 folds, embargo 24, cout 1.5 bps, donnees du
2023-06-18 au 2026-07-14:

- 17 812 bougies, 17 598 echantillons, 14 665 predictions hors echantillon ;
- seuil brut et filtre selectionnes sur validation: `0.8` ;
- tranche test: 5 866 barres ;
- 266 barres directionnelles bloquees sur 551, soit `48.28 %` ;
- strategie brute: rendement `-16.64 %`, Sharpe `-2.03`, max drawdown
  `-18.67 %`, profit factor `0.846`, 433 evenements de turnover ;
- strategie filtree: rendement `-4.22 %`, Sharpe `-0.62`, max drawdown
  `-9.97 %`, profit factor `0.959`, 286 evenements de turnover ;
- le filtre reduit donc nettement la perte et le drawdown, mais l'esperance reste
  negative et le profit factor reste inferieur a 1.

Verdict: `REJECT_LIVE_INTEGRATION`. Le filtre reste read-only. Une amelioration
relative d'une strategie perdante ne constitue pas un edge exploitable.

## Strategie de rendement attendu 24 h

La classification `DOWN/FLAT/UP` a ete remplacee, pour la recherche uniquement,
par une hypothese de regression directe du rendement futur a 24 heures:

- validation walk-forward imbriquee en 5 plis et embargo de 24 barres ;
- seuil de rendement attendu choisi dans une validation anterieure a chaque pli ;
- transactions non chevauchantes conservees 24 barres ;
- marquage a marche pendant la position ;
- cout de base de 1.5 bps par cote et financement conservateur de 1.6 bps/jour ;
- abstention complete lorsque la validation anterieure ne trouve aucun seuil ;
- achats uniquement, les ventes ayant degrade la stabilite hors echantillon ;
- ciblage causal de 15 % de volatilite annualisee, exposition plafonnee a 100 %,
  sans levier ni martingale.

Validation H1 sur les donnees du projet:

- 17 598 echantillons et 14 665 observations hors echantillon ;
- rendement compose `+36.28 %` ;
- Sharpe annualise `1.19` ;
- profit factor `1.32` ;
- max drawdown `-12.94 %` ;
- 318 transactions et exposition notionnelle moyenne `43.69 %` ;
- 4 plis positifs, 0 negatif et 1 pli sans transaction ;
- couts doubles: rendement `+18.19 %` ;
- stress a 5 bps/cote et 3.2 bps/jour: rendement `+6.22 %`, profit factor `1.07`.

Variantes rejetees:

- regression BUY/SELL: `+36.85 %`, mais seulement 2 plis positifs, drawdown
  `-29.70 %` et rendement severe `-11.95 %` ;
- filtre de momentum journalier 100 jours: Sharpe `0.78`, un pli negatif et
  rendement severe `-7.09 %`.

Verdict: `PROMOTE_TO_PAPER_TRADING`. L'integration live reste desactivee. Les
variantes ont ete comparees sur l'historique disponible; une validation paper
prospective est obligatoire avant toute nouvelle decision de promotion.

## Parite d'execution et integration paper

Le premier candidat a sortie fixe 24 h ne correspondait pas au moteur, qui
impose un stop-loss et un take-profit. Le simulateur a donc ete aligne sur
l'execution reelle:

- parcours OHLC intrabar ;
- stop prioritaire si stop et objectif sont touches dans la meme bougie ;
- sorties `STOP_LOSS`, `TAKE_PROFIT` ou `HORIZON` ;
- stop causal `max(0.5 %, 3 x ATR14)` et objectif `3R` ;
- sortie temporelle broker par `dealId` apres 24 heures ;
- meme bracket pendant la selection du seuil, les plis OOS et les stress.

Resultat H1 aligne sur 14 665 observations OOS:

- rendement `+53.33 %`, Sharpe `1.49`, profit factor `1.25` ;
- max drawdown `-14.35 %`, 553 transactions ;
- 4 plis positifs et 1 pli negatif (`-2.16 %`) ;
- stress severe: `+0.66 %`, profit factor `1.014`.

Integration ajoutee:

- artefact distinct `models/H1/expected_return_paper`, non eligible live ;
- seuil final recale sur la derniere validation: `0.30 %` ;
- strategie `expected-return-paper`, long-only, vol target 15 %, sans levier ;
- double verrou live dans la factory et le Trader ;
- refus du hot-swap automatique vers une strategie non-paper ;
- journal avec rendement attendu, seuil, couts, exposition, stop, horizon,
  barre de decision et version du modele ;
- reconciliation automatique des sorties SL/TP avant chaque decision ;
- suivi `GET /paper/validation`, objectif 100 trades clotures, sans promotion
  automatique ;
- panneaux dashboard pour le signal expected-return et la progression paper.

Verification locale controlee:

- moteur lance avec overrides `TRADING_ENABLED=false`,
  `TRADING_LOOP_ENABLED=false`, `INGEST_ENABLED=false` ;
- strategie chargee: `expected-return-paper`, `paper_only=true` ;
- preview observe: `BUY`, rendement attendu proche de `0.40 %`, exposition
  proche de `70 %`, bracket 3R, mode `PAPER` ;
- 12 tests manuels moteur, compilation Python, lint/typecheck web, lint/typecheck
  API et tests NestJS valides ;
- aucun ordre envoye pendant la verification.

Mise en service paper:

- moteur actif avec `CAPITAL_ENV=demo`, `TRADING_ENABLED=true` et boucle horaire ;
- statut effectif expose: stop minimal `0.5 %`, multiplicateur `3 x ATR14`,
  objectif `3R` ;
- premiere decision prospective journalisee, sans execution car une position
  GOLD issue de l'ancienne strategie occupe deja l'unique emplacement autorise ;
- compteur de validation initialise a `0 / 100` trades clotures et promotion
  live automatique desactivee.
