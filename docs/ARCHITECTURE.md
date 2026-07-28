# ARCHITECTURE

Dernière mise à jour : 2026-07-28 (branche `feature/ai-adaptive-scalping-engine`).

Ce document décrit ce qui EXISTE. Ce qui est prévu vit dans
[ROADMAP_AI_TRADING.md](ROADMAP_AI_TRADING.md).

## 1. Vue d'ensemble

Trois applications dans un monorepo, plus le terminal MetaTrader 5.

| Composant | Techno | Port | Rôle |
| --- | --- | --- | --- |
| `apps/engine` | Python 3.12+/FastAPI | 8000 | Données, stratégies, risque, exécution, backtest, IA |
| `apps/api` | NestJS 11 + Prisma 7 | 3001 | Proxy dashboard, rapports Telegram, relais d'alertes |
| `apps/web` | Next.js 16 + Tailwind | 3002 | Tableau de bord (polling) |
| PostgreSQL | Docker | 5433 | Persistance partagée |
| MetaTrader 5 | Terminal Windows | IPC | Cotations et exécution |

Contrainte structurante : le paquet Python `MetaTrader5` est **Windows-only**.
Le moteur tourne nativement sur le PC de l'opérateur, il n'est pas
conteneurisable pour le trading.

## 2. Flux d'une décision

```text
Boucle de trading (TRADE_INTERVAL_SECONDS)
  1. Réconciliation paper + clôtures expirées + prise de profit
  2. Bougies M1 (déclencheur) + M5/M15/H1 (contexte) depuis MT5
  3. Strategy.evaluate() -> Signal (BUY/SELL/HOLD + features + raisons)
  4. StrategyDecision insérée en base (exécutée ou non)
  5. Gardes séquentielles, chacune capable d'arrêter le cycle :
       HOLD -> stop
       stratégie paper hors compte démo -> stop
       filtre d'annonces (fail-closed) -> stop
       marché fermé -> stop
       spread > MAX_SPREAD_PCT -> stop
       compte MT5 non démo (vérifié au terminal) -> stop
  6. RiskManager.review(signal, compte, positions, stats DB)
       -> kill switch, limites jour/semaine, série de pertes, cooldowns,
          dimensionnement par distance de stop
       -> RiskDecision journalisée (approuvée OU refusée)
  7. Ordre MT5 (conversion onces->lots, filling mode détecté, SL/TP serveur)
  8. Trade inséré, décision marquée exécutée, setup marqué consommé
```

Sorties : moniteur de profit (mode scalp), SL/TP côté serveur broker, ou
horizon. Chaque clôture déclenche l'analyse post-trade (MFE/MAE, classement).

## 3. Persistance

Toutes les tables sont gérées par Prisma (`apps/api/prisma/schema.prisma`) et
écrites par le moteur en SQL brut (asyncpg).

| Table | Écrite par | Contenu |
| --- | --- | --- |
| `Candle` | moteur | OHLCV par instrument/granularité (clé composite = ingestion idempotente) |
| `Trade` | moteur | Position ouverte/fermée, bracket, features de la décision |
| `StrategyDecision` | moteur | Chaque évaluation de stratégie, exécutée ou non |
| `RiskDecision` | moteur | Chaque passage par le moteur de risque, avec le motif |
| `TradeResult` | moteur | Analyse post-trade : R, MFE/MAE, durée, classification |
| `SystemEvent` | moteur | Kill switch, broker dégradé ; `notified` pilote le relais d'alertes |
| `EquitySnapshot` | API | Photo quotidienne du compte (rapports, drawdown) |
| `User` | — | **Table morte** (authentification jamais implémentée) |

## 4. Sécurité

- **Aucune authentification utilisateur.** Les routes mutantes exigent une clé
  partagée : `API_KEY` (en-tête `x-api-key`) côté NestJS,
  `ENGINE_API_TOKEN` côté moteur. Clé absente = routes ouvertes, avec
  avertissement au démarrage — tolérable uniquement en écoute locale.
- **Écoute `127.0.0.1` par défaut** pour l'API (`API_HOST` pour surcharger).
- **CORS strict** : `http://localhost:3002` par défaut, jamais `origin: true`.
- **Validation** : `ValidationPipe` global (champs inconnus rejetés) + DTO.
- **Secrets** : uniquement en variables d'environnement, `.env` non suivis par
  git, token Telegram masqué dans les logs d'erreur.

## 5. Verrous de protection du capital

Empilés, chacun suffit à bloquer un ordre :

1. `TRADING_ENABLED=false` par défaut (kill switch statique) ;
2. kill switch dynamique persisté, verrouillé automatiquement quand une limite
   est atteinte, réactivation manuelle avec raison obligatoire ;
3. `build_strategy` refuse les stratégies paper hors `BROKER_ENV=demo` ;
4. avant chaque ordre, le type de compte est vérifié **auprès du terminal MT5**
   (une variable d'environnement peut mentir, pas le broker) ;
5. `RiskManager` fail-closed : sans statistiques de risque fiables, il refuse ;
6. filtre d'annonces fail-closed ;
7. promotion de modèle exclusivement manuelle.

## 6. Relais d'alertes

Le moteur n'a jamais le token Telegram. Il écrit un `SystemEvent` ; l'API relit
chaque minute les événements `WARNING`/`CRITICAL` non notifiés, les envoie et
les marque. Conséquences : un seul dépositaire du secret, aucune alerte perdue
si l'API redémarre, aucune alerte sur des événements de plus de 3 heures.

## 7. Ce que l'architecture ne fait PAS

- Pas de WebSocket : le dashboard fait du polling (10 à 30 s).
- Pas de Redis actif (provisionné, inutilisé).
- Pas de modèle IA dans la boucle de décision : le premier a été rejeté
  (cf. [AI_MODELS.md](AI_MODELS.md)), la stratégie déterministe décide seule.
- Pas de trading réel : modes autorisés BACKTEST / PAPER (compte démo).
