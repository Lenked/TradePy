# 🏗️ ARCHITECTURE MAP - TradePy

## 📁 Structure du projet

```
tradepy/
├── core/                 # Domaine métier & logique pure
│   ├── models.py         # Dataclasses & types partagés
│   ├── exchange/         # Interfaces & implémentations d'échanges
│   │   ├── interface.py  # Interface combinée (Live + Backtest)
│   │   └── live_interface.py  # Interface Live spécifique
│   ├── execution/        # Exécution des ordres
│   │   └── mt5_executor.py    # Implémentation MT5
│   ├── strategy/         # Stratégies de trading
│   │   └── trend_following_strategy.py  # Source of truth
│   └── autres modules... # data, portfolio, risk, etc.
├── live/                 # Orchestration du trading en direct
│   ├── runner.py         # Orchestrateur principal
│   └── watcher.py        # Surveillance des risques
├── backtest/             # Modules de backtesting
├── utils/                # Utilitaires partagés
│   └── logger.py         # Logging centralisé
├── examples/             # Scripts d'exemples (non-cœur)
│   └── mt5/              # Exemples MT5
└── config/               # Configuration
```

## 🔄 Dépendances & Règles d'import

### Règles d'architecture :
- **core** : Couche de domaine, ne dépend de rien d'autre
- **live** : Dépend de core.interfaces, pas d'implémentations spécifiques
- **backtest** : Dépend de core.interfaces
- **utils** : Utilitaires partagés, peut être utilisé partout
- **examples** : Scripts d'exemples, ne sont pas intégrés au cœur

### Interfaces :
- `LiveExchangeInterface` : Interface minimale pour le live trading
- `BacktestDataInterface` : Interface pour le backtesting
- `ExchangeInterface` : Combinaison des deux (pour compatibilité)

## 🎯 Points d'entrée

### Live Trading :
- `live.runner.LiveRunner` : Point d'entrée principal pour le live
- Dépend de `LiveExchangeInterface`, pas de MT5Executor directement
- Permet de changer d'implémentation sans modifier le runner

### Backtesting :
- `backtest.engine.BacktestEngine` : Moteur de backtesting
- Dépend de `BacktestDataInterface`

### Exemples :
- `examples/mt5/live_runner_example.py` : Exemple d'utilisation

## 🛡️ Principes de sécurité

### MT5Executor :
- `place_market_order()` : SL et TP obligatoires (safe-by-default)
- Validation des entrées avant exécution
- Logging structuré, pas de `print()` dans le code métier

### Interfaces :
- ISP respecté : interfaces séparées pour live et backtest
- Pas de `NotImplementedError` sur les chemins de production
- Type hints partout où possible

## 🏗️ Clean Architecture

### Modèles (core/models.py) :
- `AccountSnapshot`, `OrderRequest`, `OrderResult`
- Partagés entre tous les modules

### Interfaces (core/exchange/) :
- Abstraction des dépendances externes
- Facilitent les tests et la substitution

### Implémentations (core/execution/) :
- MT5Executor implémente LiveExchangeInterface
- Ne contient pas de side effects à l'import

### Orchestration (live/) :
- LiveRunner dépend d'interfaces, pas d'implémentations concrètes
- Respect du principe d'inversion de dépendance

## 📦 Organisation finale

### Cœur du framework :
- Minimal et bien organisé
- Pas de logique business dans `__init__.py`
- Pas de side effects à l'import
- Interfaces claires et séparées

### Exemples :
- Déplacés dans `/examples/`
- Ne font pas partie du cœur du framework
- Facilitent l'apprentissage sans complexifier le cœur

### Tests & Validation :
- Tous les tests passent
- Structure valide
- Syntaxe correcte
- Compatibilité descendante maintenue via `DeprecationWarning`