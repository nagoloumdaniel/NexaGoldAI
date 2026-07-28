# GESTION DU RISQUE

Dernière mise à jour : 2026-07-28.

Le moteur de risque est **indépendant des stratégies et des modèles**. Aucune
stratégie ne peut élargir une limite ; elle peut seulement réduire son
exposition (multiplicateur 0 à 1). Aucun modèle IA n'écrit de paramètre de
risque.

## 1. Ordre imposé

```text
Signal technique -> (évaluation IA) -> RiskEngine -> Exécution
```

Le `RiskManager` est le dernier rempart avant l'ordre. Il est **fail-closed** :
sans statistiques de risque fiables (base injoignable), il refuse.

## 2. Limites (apps/engine/.env)

| Variable | Défaut | Effet |
| --- | --- | --- |
| `TRADING_ENABLED` | `false` | Kill switch statique : aucun ordre |
| `MAX_RISK_PER_TRADE_PCT` | `1.0` | Budget de risque par trade (% du solde) |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Perte du jour ; atteinte -> **verrouillage** |
| `MAX_WEEKLY_LOSS_PCT` | `6.0` | Perte de la semaine ; atteinte -> **verrouillage** |
| `MAX_OPEN_POSITIONS` | `3` | Positions simultanées du bot (symbole + magic) |
| `MAX_CONSECUTIVE_LOSSES` | `4` | Série de pertes ; atteinte -> **verrouillage** |
| `COOLDOWN_AFTER_LOSS_MINUTES` | `15` | Pause après une perte |
| `COOLDOWN_AFTER_CONSECUTIVE_LOSSES_MINUTES` | `60` | Pause à partir de 2 pertes d'affilée |
| `MAX_SPREAD_PCT` | `0.001` | Spread relatif maximal à l'exécution |

### Comment la perte est mesurée (correctif majeur du 2026-07-27)

La perte du jour et de la semaine = **P&L réalisé** (trades clôturés en base,
depuis minuit / lundi UTC) **+ flottant** des positions ouvertes.

L'implémentation précédente comparait solde et équité : elle ne voyait que le
flottant. Une série de pertes *réalisées* remettait le compteur à zéro et la
limite quotidienne ne se déclenchait jamais. C'est corrigé et couvert par un
test dédié.

## 3. Dimensionnement

```text
unités = (solde × MAX_RISK_PER_TRADE_PCT / 100) / |entrée − stop| × multiplicateur
```

Le stop est d'abord élargi au minimum imposé par le broker (plus une marge)
AVANT le calcul, sinon le risque réel ne correspondrait pas à la taille. La
conversion onces → lots (contract size, pas de lot, minimum) se fait à la
frontière broker, et les unités réellement exécutées sont journalisées.

Aucune taille de lot fixe n'est codée en dur.

## 4. Kill switch dynamique

Fichier d'état persisté (`models/kill_switch.json`), donc il survit à un
redémarrage.

- **Verrouillage automatique** : limite jour/semaine atteinte, série de pertes.
- **Verrouillage manuel** : `POST /risk/lock?reason=...`.
- **Déverrouillage** : `POST /risk/unlock?reason=...` — la raison est
  **obligatoire** (refus 400 sinon). Jamais automatique, jamais par un modèle.
- **État illisible** (fichier corrompu) : verrouillage préventif au démarrage.
- Chaque bascule est historisée et **relayée en alerte Telegram**.

Le verrou bloque les **ouvertures**. Les clôtures (prise de profit, SL/TP,
réconciliation) restent permises : réduire le risque doit toujours être possible.

## 5. Interdictions permanentes

- Pas de martingale, pas de grille, pas de moyennage à la baisse.
- Pas de suppression ni d'élargissement défavorable d'un stop.
- Pas d'augmentation autonome du risque par un modèle.
- Pas d'apprentissage par exploration avec de l'argent réel.

## 6. Procédures

**Vérifier l'état** — `GET /risk/status` ou la page `/risque` du dashboard :
kill switch, consommation des limites, pertes consécutives, cooldowns.

**Arrêt d'urgence** :

```bash
curl -X POST -H "x-api-key: $API_KEY" \
  "http://127.0.0.1:8000/risk/lock?reason=Intervention%20operateur"
```

**Reprise après incident** : analyser (page `/erreurs`, `GET /risk/decisions`),
corriger la cause, puis déverrouiller avec une raison explicite. Ne jamais
déverrouiller sans avoir compris pourquoi le verrou s'est posé.

**Réconciliation** : si les positions du bot et celles du broker divergent,
`GET /trades/reconciliation` compare sans rien modifier ; la résolution ne
clôture jamais un trade sur un P&L deviné.
