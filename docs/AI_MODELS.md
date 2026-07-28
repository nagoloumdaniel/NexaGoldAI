# MODÈLES IA

Dernière mise à jour : 2026-07-28.

**État actuel : aucun modèle n'est branché dans la boucle de décision.** La
stratégie déterministe décide seule. Cette page documente le pipeline construit
et le verdict des tentatives.

## 1. Principes

- L'IA **évalue** des signaux produits par une stratégie déterministe ; elle
  n'en crée pas.
- Entraînement **hors ligne uniquement**, jamais dans le processus de trading.
- Promotion **manuelle** : un réentraînement produit un CANDIDAT, jamais un
  champion (`POST /learning/promote?version=` est le seul chemin).
- Un modèle ne peut modifier aucun paramètre de risque.
- Spec de features **partagée** entraînement/inférence, versionnée : un
  artefact dont la spec diverge est refusé au chargement.

## 2. Pipeline

```bash
cd apps/engine
# 1. Dataset : rejeu de la stratégie, capture de TOUS les candidats,
#    déduplication par setup, étiquetage par barrière
.venv\Scripts\python.exe -m app.learning.dataset_builder --days 180

# 2. Entraînement walk-forward chronologique + calibration
.venv\Scripts\python.exe -m app.learning.train_signal_quality
```

### Labels par barrière

`app/learning/labels.py` rejoue les bougies **strictement postérieures** au
signal (entrée à l'ouverture de la suivante) :

| Label | Sens |
| --- | --- |
| `TARGET_FIRST` | Objectif touché avant le stop |
| `STOP_FIRST` | Stop touché avant l'objectif |
| `AMBIGUOUS` | Les deux dans la même bougie → **compté comme perte** |
| `TIMEOUT` | Ni l'un ni l'autre dans l'horizon |
| `INVALID_DATA` | Horizon incomplet — jamais transformé en timeout optimiste |

## 3. Modèle de qualité de signal v1 — REJETÉ

Régression logistique calibrée, ensemble de folds walk-forward (l'écart entre
folds sert d'incertitude), 719 échantillons (M1 180 j + M5 dégradé 3 ans).

| Métrique | Valeur | Lecture |
| --- | --- | --- |
| AUC hors échantillon | **0.444** | < 0.5 : anti-prédictif |
| Brier | 0.228 | **Pire** que la baseline du taux de base (0.213) |
| Calibration | inversée | Décile bas : 43 % observés ; décile haut : 28 % |

Reproduit sur le dataset M5 seul (548 échantillons, AUC 0.433) : ce n'est ni un
problème de volume, ni un artefact de mélange de datasets. **Les features
testées n'ont pas de pouvoir prédictif.**

Un tableau d'« effet économique » suggérait +0.33 R au-dessus d'un seuil de
0.4 : c'est du bruit sur 69 échantillons, incohérent avec une calibration
inversée. Il n'a pas été retenu.

Artefacts marqués `REJECTED` / `eligible_for_shadow: false`, **aucun
branchement** dans le moteur — pas même en shadow, un modèle anti-prédictif
n'ajouterait que du bruit au journal.

### Piste pour une v2

Les features décrivent le **setup** (profondeur, vitesse et force du sweep,
ATR, stop) : elles disent à quoi ressemble le signal, pas dans quel
**contexte** il échoue. À tester : spread au moment du signal, distance aux
niveaux journaliers (PDH/PDL, ouverture), position dans le range de session,
proximité d'annonce, régime de volatilité.

Ne pas relancer le même modèle sur les mêmes features en espérant que plus de
données suffisent.

## 4. Modèles historiques

- **Régime de marché** (`app/signals/regime.py`) : heuristique déterministe
  explicable. Validation historique → `REJECT_LIVE_INTEGRATION` (améliore une
  stratégie perdante sans la rendre gagnante). Reste diagnostique.
- **Expected-return H1** : promu paper en 2026-07, remplacé depuis.
- **LightGBM** (registre `models/<granularité>/`) : champion/versions sur
  disque ; la promotion automatique a été **retirée** le 2026-07-27.

## 5. Ce qui manque

Modèle de coût d'exécution, détecteur d'anomalies, shadow mode challenger,
détection de dérive. Voir [ROADMAP_AI_TRADING.md](ROADMAP_AI_TRADING.md).
