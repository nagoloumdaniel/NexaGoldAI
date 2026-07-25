# NexaGold

Plateforme de trading algorithmique sur l'or (XAU/USD) pilotée par IA.

## Architecture

```text
                    ┌─────────────────────┐
                    │  apps/web (Next.js) │  ← Vercel
                    │  Tableau de bord    │
                    └─────────┬───────────┘
                              │ HTTPS / WebSocket
                    ┌─────────▼───────────┐
                    │  apps/api (NestJS)  │  ← Railway
                    │  Utilisateurs, JWT, │
                    │  notifications      │
                    └────┬───────────┬────┘
                         │           │
        ┌────────────────▼──┐   ┌────▼────────────────────┐
        │ Neon (PostgreSQL) │   │ apps/engine (FastAPI)   │  ← PC Windows local
        │ Upstash (Redis)   │   │ Données → Stratégie →   │
        └───────────────────┘   │ Risque → Exécution      │
                                └────────────┬────────────┘
                                             │ IPC (paquet MetaTrader5)
                                ┌────────────▼────────────┐
                                │ Terminal MetaTrader 5   │
                                │ C:\Program Files\...    │
                                │ (compte démo/réel)      │
                                └─────────────────────────┘
```

| Application | Rôle | Déploiement |
| --- | --- | --- |
| `apps/web` | Dashboard Next.js 16 + Tailwind | Vercel |
| `apps/api` | Backend NestJS + Prisma (utilisateurs, JWT, notifications, WebSockets) | Railway (Dockerfile) |
| `apps/engine` | Moteur de trading Python/FastAPI (MetaTrader 5, stratégies, gestion du risque) | **Windows local uniquement** (terminal MT5 requis) |
| PostgreSQL | Trades, bougies, décisions IA, équité | Neon |
| Redis | Cache, temps réel | Upstash |

## Décisions techniques (et pourquoi)

- **MetaTrader 5** comme broker (remplace Capital.com depuis 2026-07) : le
  moteur pilote le terminal MT5 installé localement
  (`C:\Program Files\MetaTrader 5`) via le paquet Python `MetaTrader5` (pont
  IPC). Conséquences assumées : **Windows uniquement**, le terminal doit
  tourner, et le moteur n'est plus déployable sur Railway/Docker — il reste
  sur le PC local, ce qui colle au fonctionnement réel (démarrage 7h, arrêt
  21h). Avantages : compte démo gratuit chez n'importe quel broker MT5,
  SL/TP stockés côté serveur du broker, exécution standard de l'industrie.
- **Dukascopy** pour l'historique profond (backtesting/entraînement) ;
  le flux MetaTrader 5 pour la décision temps réel.
- **PostgreSQL standard** (pas TimescaleDB) : Neon ne supporte pas
  l'extension, et le volume M1 (~370 000 bougies/an) reste trivial pour
  Postgres avec la clé composite de `Candle`.
- **PyTorch + LightGBM** côté IA (pas TensorFlow) : on démarre par du
  gradient boosting mesurable, le deep learning/RL viendra après validation
  du pipeline de backtesting.
- **`TRADING_ENABLED=false` par défaut** : le moteur ne peut pas envoyer
  d'ordre tant que le kill switch n'est pas explicitement levé.

## Démarrage local

### Lancement rapide (double-clic, sans terminal)

Après la première installation (ci-dessous), tout se relance en **double-cliquant
`Demarrer NexaGold (arriere-plan).vbs`** à la racine : il démarre l'infra Docker
puis les 3 services **en arrière-plan, sans aucune fenêtre**, avec les sorties
redirigées vers `logs\*.log`. `Arreter NexaGold.vbs` arrête tout.

- **Dashboard : <http://localhost:3002>** (port 3002 car 3000 est utilisé par un
  autre projet local ; pinné dans le lanceur).
- API : `localhost:3001` · Moteur : `localhost:8000`.

Sous le capot, les `.vbs` appellent `start-hidden.ps1` / `stop-auto.ps1`. Trois
tâches planifiées Windows automatisent le cycle — **fenêtre de fonctionnement :
jours ouvrés (lun-ven), 9h-20h locale** :

- `NexaGold - Start (allumage)` — à chaque ouverture de session (délai 1 min).
  Le script (appelé avec `-AutoScheduled`) ne démarre les services **que si on
  est un jour ouvré entre 9h et 20h** ; sinon il journalise le refus et
  n'allume rien. Il attend le daemon Docker (jusqu'à 4 min), lance le terminal
  MT5 si besoin, puis les 3 services. Idempotent : un service actif est ignoré.
- `NexaGold - Start 09h` — lun-ven à 9h00, si le PC est resté allumé.
- `NexaGold - Stop 20h` — tous les jours à 20h00 : rapports Telegram envoyés
  puis arrêt des services (filet de sécurité même le week-end).

Le double-clic **manuel** sur `Demarrer NexaGold (arriere-plan).vbs` reste
possible à toute heure (le garde-fou ne s'applique qu'aux lancements
automatiques). Prérequis : l'installation initiale doit avoir été faite une
fois (Docker démarré, `npm install`, venv + `pip install`, `prisma migrate`).

### Installation initiale (une fois)

Prérequis : Node 22+, Python 3.12+, Docker Desktop, **MetaTrader 5 installé**
(`C:\Program Files\MetaTrader 5\terminal64.exe`) avec un **compte démo**.

```bash
# 1. Base de données et Redis locaux
docker compose up -d

# 2. Backend NestJS
cd apps/api
cp .env.example .env
npm install
npx prisma migrate dev --name init   # crée les tables
npm run start:dev                    # http://localhost:3001/health

# 3. Moteur Python
cd apps/engine
cp .env.example .env                 # renseigner les identifiants MT5 (démo)
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000        # http://localhost:8000/health

# 4. Frontend
cd apps/web
npm install
npm run dev                          # http://localhost:3000
```

Pour obtenir les identifiants MetaTrader 5 (compte démo) : ouvrez le terminal
MT5 → **Fichier → Ouvrir un compte** → choisissez un broker (ou le serveur
d'essai MetaQuotes-Demo) → type **Démo**. À la création, MT5 affiche trois
éléments à reporter dans `apps/engine/.env` : `MT5_LOGIN` (numéro de compte),
`MT5_PASSWORD` (mot de passe principal) et `MT5_SERVER` (nom du serveur, ex.
`MetaQuotes-Demo`). Vérifiez aussi dans le Market Watch le nom exact du
symbole or chez ce broker (`XAUUSD`, `XAUUSD.a`, `GOLD`…) → `SYMBOL`, et le
décalage horaire du serveur → `MT5_UTC_OFFSET_HOURS` (heure des bougies MT5
moins heure UTC ; souvent 2 l'hiver, 3 l'été). Le moteur lance le terminal
tout seul s'il est fermé (`MT5_TERMINAL_PATH`).

### Amorcer les données et le modèle (une fois, après le 1er démarrage)

Le moteur tourne « à vide » tant qu'il n'a pas de données ni de modèle. Avec le
moteur démarré (port 8000) :

```bash
cd apps/engine
# 1. Historique profond de l'or (≈ 30-40 min pour 1 an ; ajuster --days)
.venv\Scripts\python.exe -m app.data.backfill_cli --granularity M5 --days 365
# 2. (optionnel) proxy macro EUR/USD, même période
.venv\Scripts\python.exe -m app.data.backfill_cli --granularity M5 --days 365 \
    --symbol EURUSD --divisor 100000 --instrument EURUSD
# 3. Bougies H1 dérivées des M5 (le modèle live tourne en H1)
curl -X POST "http://localhost:8000/candles/resample?source=M5&target=H1&instrument=XAUUSD"
# 4. Valider puis entraîner l'artefact strictement paper
.venv\Scripts\python.exe -m app.research.train_expected_return_paper
```

> **Migration Capital.com → MT5** : les bougies historiques sont désormais
> stockées sous la clé instrument `XAUUSD` (= `SYMBOL`). Si votre base date de
> l'époque Capital.com, re-keyez l'ancienne série `GOLD` une fois :
> `docker exec -it nexagoldai-postgres-1 psql -U nexagold -c "UPDATE \"Candle\" SET instrument='XAUUSD' WHERE instrument='GOLD';"`

Ensuite, le moteur ingère le temps réel et décide à chaque barre. La stratégie
`expected_return_paper` est verrouillée sur `BROKER_ENV=demo` **et** vérifie
auprès du terminal que le compte MT5 connecté est bien un compte démo ; son
apprentissage périodique reste désactivé pendant la validation prospective. Le
dashboard (`localhost:3002`) et les récaps Telegram reflètent le tout.

> **Granularité du modèle** : `MODEL_GRANULARITY=H1` par défaut (meilleur
> résultat mesuré). Changez-la dans `apps/engine/.env`. Le champion est par
> granularité (`models/<granularité>/`).

## Déploiement

### Neon (PostgreSQL)

1. Créer un projet sur [neon.tech](https://neon.tech), copier la connection string.
2. Appliquer le schéma : `DATABASE_URL=<neon-url> npx prisma migrate deploy` depuis `apps/api`.

### Upstash (Redis)

1. Créer une base sur [upstash.com](https://upstash.com), copier l'URL `rediss://`.

### Railway (api uniquement)

1. Créer un projet Railway relié à ce repo GitHub.
2. Service **api** : Root Directory = `apps/api` (le Dockerfile est détecté).
   Variables : `DATABASE_URL` (Neon), `REDIS_URL` (Upstash), `FRONTEND_URL`
   (URL Vercel), `JWT_SECRET`, `ENGINE_URL` (URL joignable du moteur local,
   par ex. via un tunnel, sinon les panneaux « live » resteront vides).

### Moteur (Windows local, non déployable)

⚠️ Depuis la migration MetaTrader 5, le moteur **ne peut plus être déployé sur
Railway/Docker** : le paquet `MetaTrader5` est Windows-only et dialogue avec le
terminal MT5 installé sur ce PC. Le moteur tourne donc en local (`start.ps1` /
tâches planifiées 7h-21h). Le Dockerfile de `apps/engine` ne sert plus qu'à un
mode API/lecture seule sans broker. Pendant les heures d'arrêt du bot, les
SL/TP restent actifs car ils sont stockés **côté serveur du broker MT5**.

### Vercel (web)

1. Importer le repo sur [vercel.com](https://vercel.com), Root Directory = `apps/web`.
2. Variable : `NEXT_PUBLIC_API_URL` (URL Railway de l'api).

## Notifications Telegram (récaps automatiques)

L'api envoie sur Telegram, sans intervention :

- **Récap quotidien** — chaque soir à 21h00 UTC (configurable via `REPORT_CRON`) :
  P&L du jour, solde, équité, drawdown, trades clôturés. Un `EquitySnapshot` est
  enregistré à chaque récap (il alimente aussi la courbe d'équité du dashboard).
- **Récap hebdomadaire** — chaque vendredi à 21h00 UTC (en plus du quotidien) :
  performance de la semaine, drawdown max, taux de réussite, P&L réalisé.
- **Récap mensuel** — le dernier jour du mois à 21h00 UTC : même synthèse sur le mois.

Déclenchement manuel pour tester : `POST /reports/daily/run`,
`/reports/weekly/run`, `/reports/monthly/run`.

Configuration (5 minutes) :

1. Sur Telegram, parler à **@BotFather** → `/newbot` → choisir un nom et un
   identifiant. BotFather donne le **token** → `TELEGRAM_BOT_TOKEN`.
2. Envoyer n'importe quel message à votre nouveau bot (obligatoire : un bot
   ne peut pas écrire en premier).
3. Récupérer votre chat id : ouvrir
   `https://api.telegram.org/bot<TOKEN>/getUpdates` dans un navigateur et
   lire `result[0].message.chat.id` → `TELEGRAM_CHAT_ID`.
4. Renseigner les deux variables dans `apps/api/.env` (local) et sur le
   service Railway **api** (production).

Les récaps nécessitent que le moteur (`ENGINE_URL`) soit démarré avec des
identifiants MT5 valides — c'est lui qui fournit solde et équité.

## Pipeline de données (phase 1)

Le moteur ingère les bougies de l'or depuis MetaTrader 5 dans la table `Candle`
(écriture directe via asyncpg, en partageant `DATABASE_URL` avec l'api). La
clé composite `(instrument, granularity, time)` rend l'ingestion idempotente.

- **Ingestion continue** : une boucle de fond rafraîchit les dernières bougies
  de chaque granularité toutes les `INGEST_INTERVAL_SECONDS`. Démarre
  automatiquement si la base est joignable et MT5 configuré.
- **Backfill historique** : remonte le temps par fenêtres de 900 bougies pour
  amorcer le backtesting.

Variables (toutes optionnelles, valeurs par défaut indiquées) :

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `INGEST_ENABLED` | `true` | active la boucle de fond |
| `INGEST_GRANULARITIES` | `M1,M5,M15` | granularités ingérées |
| `INGEST_INTERVAL_SECONDS` | `60` | période du rafraîchissement |
| `INGEST_RECENT_COUNT` | `50` | bougies rafraîchies à chaque tick |

Endpoints (moteur, port 8000) :

```bash
# état du pipeline (base connectée, boucle active)
curl http://localhost:8000/health
# refresh immédiat des dernières bougies
curl -X POST http://localhost:8000/ingest/run
# backfill court depuis MT5 (granularité + nb de jours, max 60)
curl -X POST "http://localhost:8000/ingest/backfill?granularity=M5&days=2"
# backfill profond depuis Dukascopy (ticks → bougies ; M1/M5/M15/M30/H1)
curl -X POST "http://localhost:8000/ingest/dukascopy?granularity=M5&days=3"
# couverture par granularité (count + plage temporelle)
curl http://localhost:8000/candles/stats
```

### Deux sources, une seule série

- **Dukascopy** (`/ingest/dukascopy`) : source de l'**historique profond** pour
  le backtesting. Télécharge les fichiers tick `.bi5` (un par heure, LZMA) en
  pur stdlib, les agrège en bougies. Symbole `XAUUSD`, prix ÷ 1000.
- **MetaTrader 5** (boucle continue + `/ingest/backfill`) : le **temps réel** et
  les bougies récentes (Dukascopy publie avec un délai).

Les deux écrivent dans la même série `(XAUUSD, granularité, time)` : là où
elles se recouvrent, la dernière écriture gagne. Les prix concordent (OHLC) ;
la sémantique du **volume** diffère (MT5 = tick volume, Dukascopy = nombre de
ticks — proches en pratique). ⚠️ MT5 horodate en **heure serveur du broker**,
pas en UTC : réglez `MT5_UTC_OFFSET_HOURS` (souvent 2 l'hiver, 3 l'été) pour
que les bougies MT5 s'alignent sur l'historique Dukascopy (UTC), sinon les
features dépendantes de l'heure seront décalées. Usage recommandé : Dukascopy
pour amorcer l'historique, puis la boucle MT5 pour entretenir le présent.

## Backtesting & modèle (phase 2)

Module de recherche dans [apps/engine/app/research/](apps/engine/app/research/) :
`features.py` (indicateurs techniques causaux), `labeling.py` (cible 3 classes),
`backtest.py` (validation walk-forward LightGBM + backtest PnL), `run.py` (CLI).

Deux méthodes de labelling :

- **fixed** : UP/DOWN si le rendement futur dépasse ±seuil.
- **triple_barrier** : barrières haute/basse à ±`vol_mult` × volatilité récente,
  plus une barrière temporelle ; le label est la première barrière touchée
  (high/low intrabar). Volatilité-adaptatif et sensible au chemin.

```bash
cd apps/engine
.venv\Scripts\python.exe -m app.research.run --granularity M5 \
    --labeling triple_barrier --horizon 24 --vol-mult 1.5 --folds 5
```

Le CLI charge les bougies depuis la base, évalue le modèle en **walk-forward**
(chaque barre de test n'est prédite que par un modèle entraîné sur des barres
strictement antérieures — pas de fuite de données), puis simule un backtest
long/short avec coûts de transaction. Il écrit `models/<granularité>/` :
`model.joblib` (modèle final), `meta.json`, `report.json`. Métriques produites :
accuracy, F1 macro, matrice de confusion, et côté PnL Sharpe annualisé, max
drawdown, profit factor, win rate, exposition.

[expected_return_strategy.py](apps/engine/app/strategy/expected_return_strategy.py)
charge l'artefact séparé `models/H1/expected_return_paper`. Il prédit directement
le rendement à 24 h, ne prend que les achats au-dessus du seuil validé et cible
15 % de volatilité annualisée sans levier.

### Filtre de confiance, validation séparée, macro

- **Filtre de confiance** : `backtest.run` balaie des seuils et ne prend
  position que si la probabilité du modèle dépasse le seuil. Choisi sur une
  **slice de validation** puis évalué sur une **slice de test held-out** (pas de
  fuite). Un **embargo** (purge) sépare train et test pour empêcher les labels
  futurs de fuiter. Le seuil retenu est sauvegardé en `meta.json` et appliqué en
  live par `LightGBMStrategy` (en dessous → HOLD).
- **Features macro** : EUR/USD (proxy inverse du dollar) aligné sur l'or —
  rendements, volatilité, corrélation glissante. Activées par config ; le Trader
  récupère la macro en direct (sinon HOLD par sécurité). *Mesuré : EUR/USD seul
  n'apporte pas d'edge clair — un vrai signal macro demanderait taux réels/DXY/
  sentiment.*
- **Granularité** : le système entraîne par granularité ; H1 donne le meilleur
  ratio signal/coût.

> **Évolution du modèle.** Validation H1 walk-forward imbriquée :
>
> | Étape | Sharpe |
> | --- | --- |
> | Baseline phase 2 (M5, 30 j, 20 features, fixe) | ≈ −34 |
> | + 1 an de données + ~30 features | ≈ −17 |
> | + filtre de confiance | ≈ −3 |
> | Classification H1 actuelle | −2,03 (rejetée) |
> | Régression 24 h long-only + vol target | 1,19 |
> | **+ bracket max(0,5 %, 3×ATR), objectif 3R** | **1,49** |
>
> Le candidat final affiche +53,33 %, Sharpe 1,49, profit factor 1,25 et max
> drawdown −14,35 % sur 14 665 observations OOS. Un pli récent reste négatif et
> le stress de coûts sévère n'est positif que de +0,66 % : ces chiffres autorisent
> uniquement une validation paper prospective, jamais une conclusion de gain.

## Paper trading (phase 3)

La boucle [trader.py](apps/engine/app/execution/trader.py) exécute, à intervalle
régulier, le cycle complet **données → signal → risque → ordre** sur le compte
démo :

1. réconcilie les sorties SL/TP, ferme à 24 h les positions paper expirées, puis
   interroge la régression expected-return ;
2. **journalise chaque décision** dans `StrategyDecision` (exécutée ou non) —
   c'est le « pourquoi » de l'IA, et le jeu de données du réentraînement ;
3. calcule le stop `max(0,5 %, 3×ATR)`, l'objectif `3R` et applique au sizing
   de risque le multiplicateur causal de volatilité, plafonné à 100 % ;
4. n'envoie un ordre que si le risque approuve, `TRADING_ENABLED=true`,
   `BROKER_ENV=demo`, le compte MT5 connecté est bien un compte **démo**, et
   le spread courant reste sous `MAX_SPREAD_PCT`.

Par défaut `TRADING_ENABLED=false` : la boucle tourne, calcule et journalise
les décisions sur le compte démo **sans jamais y toucher**. On accumule un
journal honnête de ce que le bot *ferait*, avant de lever le kill switch.

```bash
curl http://localhost:8000/trade/status          # stratégie, kill switch, état boucle
curl -X POST http://localhost:8000/trade/step    # une itération immédiate
curl "http://localhost:8000/decisions/recent?limit=20"
```

Variables (défauts) : `TRADING_LOOP_ENABLED=true`, `TRADE_INTERVAL_SECONDS=300`,
`STRATEGY_NAME=expected_return_paper`, `MODEL_GRANULARITY=H1`, `DECISION_CANDLES=200`,
`STOP_LOSS_PCT=0.005`, `RISK_REWARD_RATIO=1.5`, et le kill switch
`TRADING_ENABLED=false`.

Pour `expected_return_paper`, les paramètres de l'artefact remplacent les deux
valeurs globales de secours: stop `max(0,5 %, 3 x ATR14)` et objectif `3R`.
`GET /trade/status` expose ces valeurs effectives.

Le statut prospectif est disponible via `GET /paper/validation` et
`GET /dashboard/paper-validation`. La revue devient éligible après 100 trades
clôturés, sans promotion automatique. `expected_return_paper` refuse de charger
si `BROKER_ENV=live`, même lorsque `TRADING_ENABLED=true`.

Gardes d'exécution supplémentaires (défauts sûrs) :

- `MAX_SPREAD_PCT=0.001` — aucun ordre si le spread relatif dépasse 0,1 %
  (rollover, annonces, faible liquidité) ;
- gate d'**espérance nette** : un signal au-dessus du seuil mais sous les
  coûts estimés (spread + financement sur l'horizon) devient HOLD ;
- `REGIME_FILTER_ENFORCED=false` — le filtre de régime reste journalisé en
  shadow ; passer à `true` l'applique réellement (après validation) ;
- `EXPECTED_RETURN_ALLOW_SHORT=false` — le côté SELL, rejeté par la validation
  historique, reste désactivé par défaut.

## Dashboard (phase 4)

L'API NestJS expose les données au frontend (module
[dashboard](apps/api/src/dashboard/)) : lecture de la base via Prisma (bougies,
décisions, trades, équité) et proxy du moteur pour le compte/positions en
direct.

```bash
curl http://localhost:3001/dashboard/summary    # compte, drawdown, compteurs
curl "http://localhost:3001/dashboard/candles?granularity=M5&limit=300"
curl "http://localhost:3001/dashboard/decisions?limit=50"
curl http://localhost:3001/dashboard/trades
curl http://localhost:3001/dashboard/analytics  # win rate, profit factor, équité
```

Le dashboard Next.js ([apps/web](apps/web/src/)) consomme ces endpoints
(rafraîchissement par polling) : cartes de stats (solde, NAV, P&L, drawdown,
nb de décisions, positions), **graphique chandelier de l'or** (TradingView
Lightweight Charts), flux des **décisions IA avec leurs raisons**, et historique
des trades. Variable : `NEXT_PUBLIC_API_URL` (URL de l'API).

```bash
cd apps/web
npm run dev   # http://localhost:3000 (API sur 3001 + moteur sur 8000 requis)
```

## Boucle d'apprentissage (phase 5)

Le moteur sait se réentraîner et choisir le meilleur modèle tout seul
([apps/engine/app/learning/](apps/engine/app/learning/)). À chaque round,
plusieurs **configurations candidates** (horizons / seuils de labelling
différents) sont évaluées en walk-forward sur les **données les plus récentes** ;
la meilleure (par Sharpe out-of-sample) est entraînée sur tout l'historique,
enregistrée comme nouvelle **version** et promue **champion**. Les configs
moins bonnes sont laissées de côté — « comparer, renforcer la meilleure,
abandonner les moins efficaces ».

- **Registre versionné** ([registry.py](apps/engine/app/learning/registry.py)) :
  `models/<granularité>/registry.json` + un dossier par version
  (`model.joblib`, `meta.json`, `report.json`).
- **Hot-swap** : quand un nouveau champion est promu, la stratégie de la boucle
  de trading est rechargée à chaud, sans redémarrage.
- **Réentraînement périodique** : boucle de fond optionnelle
  (`LEARNING_ENABLED`, défaut **false** car l'entraînement est lourd ;
  `LEARNING_INTERVAL_SECONDS`, défaut quotidien).

```bash
curl -X POST http://localhost:8000/learning/retrain   # un round, renvoie le classement
curl http://localhost:8000/learning/registry          # champion + versions
```

Le dashboard affiche le panneau **« Modèles & apprentissage »** (champion +
historique des versions avec Sharpe et accuracy), via `/dashboard/models`.

> Exemple réel (1 an de M5, 5 approches) : le système a promu
> `fixed, horizon=24, seuil=0.002` (Sharpe −17,3) — meilleur PnL que les
> variantes triple-barrier, qui pourtant atteignent une accuracy supérieure
> (~50 %). La sélection par Sharpe privilégie donc le PnL net, pas la seule
> précision de classification. Sans edge net, le « meilleur » reste perdant.

## Feuille de route

1. ✅ **Pipeline de données** : ingestion continue MetaTrader 5 → table
   `Candle`, backfill historique Dukascopy. *(fait)*
2. ✅ **Backtesting + premier modèle** : features techniques, LightGBM,
   validation walk-forward (Sharpe, drawdown, profit factor). *(infrastructure
   faite ; le baseline n'a pas d'edge, à itérer)*
3. ✅ **Paper trading** : boucle complète données → signal → risque → ordre sur
   compte démo, journalisation de chaque décision (`StrategyDecision`). *(fait,
   kill switch actif)*
4. ✅ **Dashboard** : positions, historique, analytics, raisons des décisions
   IA, graphique chandelier. *(fait)*
5. ✅ **Boucle d'apprentissage** : réentraînement périodique, comparaison de
   configurations (champion/challenger), promotion automatique. *(fait ;
   exploration RL/PPO en option future)*

Le passage en réel (`BROKER_ENV=live` + compte MT5 réel) n'est envisagé
qu'après plusieurs semaines de paper trading aux métriques stables. Rappel
important : le backtest 2023-2026 à coûts réalistes n'a montré **aucun edge
net** — le mode démo sert à mesurer honnêtement, pas à préparer un passage en
réel imminent.
