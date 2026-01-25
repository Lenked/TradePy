# 📘 Documentation du squelette de projet
## Bot de trading IA – Python

> **Phase** : Analyse & Conception  
> **Objectif** : Définir une structure de projet claire, maintenable et évolutive avant toute implémentation lourde  
> **Principe** : Séparation stricte des responsabilités (clean architecture)

---

## 🎯 Finalité du squelette

Ce squelette sert à :
- transformer l’analyse fonctionnelle en structure technique
- éviter le code spaghetti
- permettre l’évolution **rule-based → IA (RL)** sans refonte
- faciliter les tests, le backtesting et le passage en réel

👉 Aucun algorithme complexe n’est implémenté à ce stade.

---

## 🧱 Vue globale de l’architecture

```
trading-bot/
│
├── config/
│   ├── settings.yaml
│   ├── risk.yaml
│   └── assets.yaml
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── features/
│
├── core/
│   ├── exchange/
│   ├── indicators/
│   ├── strategy/
│   ├── portfolio/
│   ├── risk/
│   └── execution/
│
├── backtest/
│   ├── engine.py
│   ├── metrics.py
│   └── reports.py
│
├── ai/
│   ├── env/
│   ├── agent/
│   ├── reward/
│   └── training/
│
├── live/
│   ├── runner.py
│   ├── watcher.py
│   └── notifier.py
│
├── utils/
│   ├── logger.py
│   ├── time.py
│   └── helpers.py
│
├── main.py
└── README.md
```

---

## 📂 Détail des dossiers et responsabilités

### 1️⃣ `config/`

**Rôle** : Centraliser tous les paramètres modifiables sans toucher au code

- `settings.yaml` : mode (backtest/live), exchange, timeframe, capital initial
- `risk.yaml` : règles de gestion du risque
- `assets.yaml` : actifs tradés

🎯 Avantage : reproductibilité des expériences

---

### 2️⃣ `data/`

**Rôle** : Gestion du cycle de vie des données de marché

- `raw/` : données brutes (API, CSV)
- `processed/` : données nettoyées
- `features/` : données enrichies (indicateurs)

⚠️ Aucune logique de trading ici

---

### 3️⃣ `core/`

Cœur métier du bot (indépendant de l’IA)

---

#### 🔹 `core/exchange/`

- Interface d’accès aux marchés (API)
- Abstraction : backtest ≠ live

---

#### 🔹 `core/indicators/`

- Calcul des indicateurs techniques
- Fonctions pures et testables

---

#### 🔹 `core/strategy/`

**Rôle** : Génération des signaux

Interface commune :
- BUY
- SELL
- HOLD

👉 Les stratégies IA devront respecter cette interface

---

#### 🔹 `core/portfolio/`

**Rôle** : Gestion du capital

- solde
- positions ouvertes
- PnL
- equity

---

#### 🔹 `core/risk/`

**Rôle critique** : protection du capital

- validation ou refus d’un trade
- contrôle du drawdown
- respect du risk per trade

> Le risk manager peut bloquer une décision IA

---

#### 🔹 `core/execution/`

- Simulation des ordres
- Gestion des frais
- Slippage

---

### 4️⃣ `backtest/`

**Rôle** : Évaluation des performances

- `engine.py` : moteur de backtest
- `metrics.py` : calcul des métriques
- `reports.py` : génération de rapports

📊 Résultats attendus : comparables à un journal de trading réel

---

### 5️⃣ `ai/`

**Rôle** : Intelligence artificielle (optionnelle)

---

#### 🤖 `ai/env/`

- Environnement de trading (TensorTrade / Gym)
- Définition des observations et actions

---

#### 🤖 `ai/agent/`

- Algorithmes RL (PPO, A2C, DQN)

---

#### 🤖 `ai/reward/`

**Cœur du comportement IA**

- définition de la reward function
- pénalités et bonus

---

#### 🤖 `ai/training/`

- scripts d’entraînement
- sauvegarde des modèles

---

### 6️⃣ `live/`

**Rôle** : Exécution temps réel

- `runner.py` : boucle principale
- `watcher.py` : surveillance du risque
- `notifier.py` : alertes (Telegram, Discord)

⚠️ Kill switch obligatoire

---

### 7️⃣ `utils/`

**Rôle** : outils transversaux

- logging
- gestion du temps
- helpers

---

### 8️⃣ `main.py`

**Point d’entrée unique**

- choix du mode : backtest / paper / live
- orchestration des modules

---

## 🧠 Principes d’architecture appliqués

- Single Responsibility Principle
- Séparation métier / infrastructure
- IA non intrusive
- Testabilité maximale

---

## 📌 Livrables de cette phase

- Arborescence claire
- Documentation technique
- Base saine pour implémentation

---

## 🧭 Étape suivante recommandée

1. Générer le projet vide (repo)
2. Implémenter une stratégie simple
3. Valider le pipeline sans IA
4. Introduire l’IA progressivement

---

✍️ *Ce document sert de référence de conception pour tout le projet.*

