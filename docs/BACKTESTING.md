# BACKTESTING

Dernière mise à jour : 2026-07-28.

Deux outils coexistent :

- **Backtest évènementiel** (`app/backtesting/`) — rejeu bougie par bougie pour
  les stratégies à règles. C'est celui qui a rendu le verdict sur
  `liquidity_sweep`.
- **Walk-forward LightGBM** (`app/research/`) — hérité, pour les modèles de
  classification/régression sur features.

## 1. Backtest évènementiel

```bash
cd apps/engine
.venv\Scripts\python.exe -m app.backtesting.run --days 180
.venv\Scripts\python.exe -m app.backtesting.run --days 180 --risk-reward 3 --spread-pct 0.00024
```

Options : `--days`, `--risk-reward`, `--spread-pct`, `--slippage-pct`,
`--commission-pct`, `--risk-pct`, `--window`, `--sessions`, `--no-sessions`,
`--no-retest`, `--base-granularity {M1,M5}`, `--max-holding-bars`.

### Ce que le moteur simule

- **Zéro lookahead** : à chaque clôture M1, les fenêtres M5/M15/H1 sont
  reconstruites depuis le M1 et tronquées aux bougies closes.
- **Latence** : le signal émis à la clôture d'une bougie est exécuté à
  **l'ouverture de la suivante**.
- **Coûts** : demi-spread à l'entrée ET à la sortie, slippage sur les fills au
  marché et sur les stops (toujours en notre défaveur), commission optionnelle.
- **Bracket intrabar pessimiste** : si le stop et l'objectif sont touchés dans
  la même bougie, le **stop l'emporte** (l'ordre réel est inconnaissable sans
  ticks).
- **Une position à la fois**, parité avec `MAX_OPEN_POSITIONS=1`.
- Timeout de sécurité, MFE/MAE en R suivis pour chaque trade.

### Sorties

`reports/backtests/<RUN_ID>/` : `summary.json` (métriques, sorties,
distribution horaire, histogramme des raisons de HOLD), `trades.csv`,
`equity_curve.csv`. Le dossier `reports/` est hors git.

### Mode dégradé

`--base-granularity M5` remplace le déclencheur M1 par du M5. C'est une
**approximation assumée** pour tester des périodes sans historique M1 : la
calibration sur fenêtre commune montre que la finesse M1 vaut ~0.17 R
d'espérance. À lire comme un test de régime, pas comme une simulation fidèle.

## 2. Données

```bash
# Historique profond depuis le terminal MT5 (rapide, profondeur limitée)
.venv\Scripts\python.exe -c "import asyncio; ..."   # cf. README

# Historique Dukascopy (ticks -> bougies, profond mais rate-limité)
.venv\Scripts\python.exe -m app.data.backfill_cli --granularity M1 --days 180
```

Contrôler la qualité avant de conclure quoi que ce soit :

```bash
curl "http://127.0.0.1:8000/data/quality?granularity=M1&source=db"
```

Le validateur détecte trous (hors fermeture week-end), bougies malformées,
doublons, désordre, données figées et périmées, et rend un score 0–1
(seuil de validité 0.80). Le jeu M1 utilisé pour le verdict scorait 0.939.

## 3. Limites connues

- Spread **constant** configurable, pas encore variable par heure — or le
  spread XAUUSD s'élargit au rollover et sur annonces. Un backtest à spread
  moyen est donc optimiste sur ces créneaux.
- Les fenêtres d'annonces ne sont pas simulées (le filtre existe en live).
- Pas de rejets d'ordre ni de freeze level simulés.
- Pas encore de tests de robustesse systématiques (grille de paramètres).

## 4. Discipline

- Un backtest rentable **ne suffit pas** : il faut la stabilité sur plusieurs
  fenêtres, la résistance au doublement des coûts, un drawdown conforme, puis
  une validation paper prospective.
- Toute variante testée doit être rapportée, y compris les défavorables —
  sinon on sélectionne du bruit.
- Rappel projet : le Sharpe +3.27 de 2023-2026 obtenu en 2026-06 était un
  mirage. Un chiffre flatteur mérite d'abord de la méfiance.
