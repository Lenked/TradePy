# Réglages stratégie et risque – Amélioration des performances

Ce document décrit les réglages concrets appliqués pour limiter la stagnation du PnL (trop de sorties en stop-loss, symboles perdants).

## Contexte

- **Problème observé** : PnL qui stagne autour de 500–600 $ après un pic, avec ~57 % des trades fermés en **stop-loss** et ~40 % en take-profit.
- **Symboles les plus perdants** : USOILm (forte contribution aux pertes), puis NVDAm et EURUSDm.
- **Symboles rentables** : BTCUSDm, XAUUSDm.

## Modifications appliquées

### 1. Stop-loss / Take-profit par symbole (`config/settings.yaml`)

- **USOILm** : avant `sl_atr: 0.6`, `tp_atr: 0.9` (trop serré → beaucoup de SL).  
  **Nouveau** : `sl_atr: 1.5`, `tp_atr: 2.5` pour laisser plus de marge au trade.

- **XAUUSDm** : pas d’override auparavant (défaut 2.0 / 3.0).  
  **Ajout** : `sl_atr: 2.5`, `tp_atr: 3.5` pour mieux absorber les spikes et améliorer le ratio gain/perte.

- Les autres symboles gardent les valeurs par défaut : `sl_atr_multiplier: 2.0`, `tp_atr_multiplier: 3.0`.

### 2. Filtres RSI (éviter surachat / survente)

Dans **stratégie** (`TrendFollowingStrategy`) et **config** :

- **rsi_buy_max** (ex. 70) : pas d’achat si RSI ≥ 70 (éviter les entrées en surachat).
- **rsi_sell_min** (ex. 30) : pas de vente si RSI ≤ 30 (éviter les entrées en survente).

Réglages dans `config/settings.yaml` :

```yaml
strategy:
  rsi_buy_max: 70
  rsi_sell_min: 30
```

Pour désactiver : commenter ou retirer ces lignes (comportement comme avant).

### 3. Désactiver un symbole (`symbols_disabled`)

Pour exclure temporairement un symbole (ex. USOILm) sans changer le code :

Dans `config/settings.yaml`, à la **racine** du fichier :

```yaml
symbols_disabled:
  - USOILm
```

La liste des symboles du jour (via `symbol_schedule` ou le défaut) est filtrée : les symboles listés dans `symbols_disabled` ne sont plus tradés.

## Fichiers modifiés

| Fichier | Changement |
|--------|------------|
| `config/settings.yaml` | SL/TP overrides USOILm et XAUUSDm, `rsi_buy_max` / `rsi_sell_min`, option `symbols_disabled` (commentée par défaut). |
| `core/strategy/trend_following_strategy.py` | Paramètres `rsi_buy_max` / `rsi_sell_min` et logique HOLD si RSI hors bande. |
| `core/utils/symbol_schedule.py` | Prise en charge de `symbols_disabled` pour filtrer la liste des symboles du jour. |
| `main.py` | Passage de `rsi_buy_max` et `rsi_sell_min` depuis la config vers la stratégie. |

## Recommandations

1. **Tester d’abord** avec les nouveaux SL/TP et les filtres RSI sans désactiver de symbole, puis comparer le taux de SL et le PnL.
2. Si **USOILm** reste très perdant : activer `symbols_disabled: [USOILm]` pour une période et comparer les performances.
3. Ajuster **rsi_buy_max** / **rsi_sell_min** (ex. 65/35 pour des entrées plus strictes) si trop de mauvais signaux restent pris.
