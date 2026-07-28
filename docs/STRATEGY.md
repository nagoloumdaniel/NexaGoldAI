# STRATÉGIES

Dernière mise à jour : 2026-07-28.

Deux stratégies sont utilisables ; **une seule est active** à la fois
(`STRATEGY_NAME` dans `apps/engine/.env`). Toutes sont `paper_only` : la
factory refuse de les charger hors `BROKER_ENV=demo`.

| Nom | `STRATEGY_NAME` | Statut |
| --- | --- | --- |
| Liquidity sweep | `liquidity_sweep` | **Active en paper depuis le 2026-07-28** |
| Scalp M5 multi-timeframe | `scalp_m5` | Disponible, remplacée |
| Expected-return H1 | `expected_return_paper` | Historique, non recommandée |
| LightGBM | `lightgbm` | Historique (registre de modèles) |

## 1. LIQUIDITY_SWEEP_TREND_CONTINUATION (active)

Code : [`apps/engine/app/strategy_v2/`](../apps/engine/app/strategy_v2/).
Prérequis : `MODEL_GRANULARITY=M1` et `M1` dans `INGEST_GRANULARITIES`.

### Idée

Le prix perce brièvement un creux (ou sommet) de référence — là où
s'accumulent les stops — puis **réintègre rapidement**. La liquidité prise, le
mouvement reprend dans le sens de la tendance supérieure. On entre sur le
retest de la zone cassée, pas sur l'impulsion.

### Pipeline

| Timeframe | Rôle | Conditions |
| --- | --- | --- |
| H1 | Contexte | Tendance structurelle (HH/HL ou LH/LL), volatilité non extrême |
| M15 | Alignement | Même tendance que H1, aucun CHoCH opposé |
| M5 | Zones | Niveaux de liquidité (swings + égalités), sweep + réintégration rapide |
| M1 | Déclenchement | Shift de microstructure puis **retest** avec bougie de rejet |

Aucune bougie en cours de formation n'est utilisée, sur aucun timeframe.

### Machine à états

`IDLE → CONTEXT_VALIDATED → ZONE_DETECTED → SWEEP_DETECTED →
REINTEGRATION_CONFIRMED → STRUCTURE_SHIFT_CONFIRMED → WAITING_RETEST →
READY_TO_EXECUTE`, avec sorties `REJECTED` / `COOLDOWN` / `SYSTEM_LOCKED`.

Chaque transition est horodatée, motivée et historisée. Une transition
interdite lève une erreur contrôlée — jamais une exécution.

### Invalidations

Hors session autorisée, contexte H1 non directionnel, M15 non aligné, CHoCH
contraire, volatilité H1 extrême, aucun sweep récent réintégré, sweep trop
profond (vraie cassure) ou trop superficiel (bruit), réintégration trop lente,
pas de shift M1, retest non confirmé, mouvement déjà étendu au-delà du retest,
setup déjà exécuté.

### Paramètres

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `SWEEP_MIN_RISK_REWARD` | `3.0` | TP = RR × distance de stop (calibré par backtest) |
| `SWEEP_REQUIRE_RETEST` | `true` | Retest obligatoire (sans lui : espérance négative) |
| `SESSIONS_ENABLED` | `true` | Restriction aux sessions |
| `ALLOWED_SESSIONS` | `LONDON,NEW_YORK` | Fenêtres UTC autorisées |
| `AVOID_SESSION_EDGES_MINUTES` | `5` | Exclusion des ouvertures/clôtures |

Stop **structurel** : sous (ou sur) l'extrême du sweep, plus une marge ATR.

### Validation

Backtest évènementiel sur 180 jours de M1 (cf. [BACKTESTING.md](BACKTESTING.md)) :

| Configuration | Trades | Réussite | Espérance | PF |
| --- | --- | --- | --- | --- |
| RR 2 | 125 | 33.6 % | **−0.04 R** | 0.94 |
| RR 3 | 110 | 29.1 % | **+0.12 R** | 1.16 |
| RR 3, coûts ×2 | 111 | 28.8 % | +0.06 R | 1.07 |
| RR 3, 90 derniers jours | 57 | 29.8 % | +0.13 R | 1.17 |
| Sans retest | 145 | 33.1 % | −0.09 R | 0.88 |

Test de régime 2023-2026 en mode dégradé (M5) : −0.03 R, sans effondrement.

**Statut : PAPER_CANDIDATE.** 110 trades, c'est moins d'un écart-type au-dessus
de zéro : encourageant, **pas démontré**. La validation paper prospective
(100 trades) est le prochain juge. Le trading réel reste verrouillé.

Faiblesse connue : les entrées entre 16 h et 18 h UTC sont nettement négatives
dans le backtest ; l'échantillon est trop petit pour filtrer sans sur-ajuster.

## 2. Scalp M5 multi-timeframe (disponible)

Code : [`apps/engine/app/strategy/scalp_mtf.py`](../apps/engine/app/strategy/scalp_mtf.py).

Votes de tendance EMA20/50 + RSI14 + MACD sur M15/M30/H1, entrée M5 sur
déclencheur EMA9/21 + RSI7, **clôture dès le premier profit net** (moniteur
toutes les 5 s). Un tuner adaptatif borné ajuste les paramètres tous les
8 trades clôturés, chaque changement étant journalisé avec sa raison.

**Jamais backtestée** — validation paper prospective uniquement. Le tuner
module la taille de position, ce qui est en tension avec la règle « l'IA ne
touche pas au risque » ; ce transfert vers le RiskEngine est planifié.

## 3. Changer de stratégie

```bash
# apps/engine/.env
STRATEGY_NAME=liquidity_sweep      # ou scalp_m5
MODEL_GRANULARITY=M1               # M5 pour scalp_m5
INGEST_GRANULARITIES=M1,M5,M15,M30,H1
```

Puis redémarrer le moteur. La factory refuse les combinaisons incohérentes
(`liquidity_sweep` exige `M1`) et toute stratégie paper hors compte démo.
