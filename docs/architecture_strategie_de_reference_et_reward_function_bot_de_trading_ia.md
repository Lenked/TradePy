# 📐 Architecture, Stratégie de référence et Reward Function
## Bot de trading IA – Documentation de conception

> **Phase** : Analyse & Conception approfondie  
> **Objectif** : Formaliser le fonctionnement interne du bot avant toute implémentation

---

# 1️⃣ Diagramme d’architecture
## Flux Data → Strategy → Risk → Execution

### 🧠 Vue conceptuelle

```
        ┌──────────────┐
        │  Market Data │
        │ (OHLCV)      │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │  Features &  │
        │ Indicators   │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │   Strategy   │
        │ (Signals)    │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │ Risk Manager │
        │ (Validation) │
        └──────┬───────┘
               │
       Accepted│Rejected
               │
               ▼
        ┌──────────────┐
        │  Execution   │
        │ (Orders)     │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │  Portfolio   │
        │ (PnL, Equity)│
        └──────────────┘
```

---

### 🔎 Rôle de chaque étape

- **Market Data** : source unique de vérité (aucun accès futur)
- **Features** : transformation du bruit en information
- **Strategy** : logique décisionnelle
- **Risk Manager** : garde-fou absolu
- **Execution** : simulation ou envoi réel d’ordres
- **Portfolio** : mémoire financière du système

> 🔑 L’IA, si présente, se branche uniquement au niveau **Strategy**

---

# 2️⃣ Documentation d’une stratégie de référence (sans IA)

## 🎯 Objectif

Créer une **stratégie simple, robuste et compréhensible** servant de benchmark.

---

## 📊 Type de stratégie

### 👉 Trend Following (EMA + RSI)

Pourquoi ce choix ?
- largement documentée
- robuste sur plusieurs marchés
- peu sensible au sur-optimisation

---

## 🧩 Indicateurs utilisés

| Indicateur | Rôle |
|-----------|------|
| EMA 50 | Tendance court/moyen terme |
| EMA 200 | Tendance long terme |
| RSI 14 | Momentum / surachat-survente |
| ATR | Volatilité / stop adaptatif |

---

## 📥 Règles d’entrée

### Signal BUY
- EMA 50 > EMA 200
- RSI > 50
- Prix au-dessus de EMA 50

### Signal SELL
- EMA 50 < EMA 200
- RSI < 50
- Prix sous EMA 50

### HOLD
- Aucune condition remplie

---

## 📤 Règles de sortie

- Stop-loss basé sur ATR
- Take-profit ratio 1:2
- Sortie forcée si signal inverse

---

## ⚠️ Risk Management associé

- Risk par trade : 1 % du capital
- Une seule position par actif
- Pas de pyramiding

---

## 📈 Avantages et limites

### ✅ Avantages
- simple à implémenter
- interprétable
- bon benchmark

### ❌ Limites
- faible en marché range
- drawdown possible prolongé

---

# 3️⃣ Documentation théorique de la Reward Function

## 🤖 Contexte

La reward function définit **le comportement appris par l’agent IA**.

> Une mauvaise reward = un bot dangereux

---

## ❌ Reward naïve (à éviter)

```
reward = profit
```

Effets négatifs :
- overtrading
- drawdown massif
- instabilité

---

## ✅ Philosophie d’une bonne reward

La reward doit encourager :
- la survie
- la régularité
- la discipline

Et pénaliser :
- le risque excessif
- l’avidité
- l’instabilité

---

## 🧮 Composantes recommandées

### 1. Profit normalisé

- éviter les récompenses explosives

### 2. Drawdown penalty

- pénaliser les pertes cumulées

### 3. Overtrading penalty

- limiter la fréquence excessive des trades

### 4. Volatility penalty

- favoriser une equity curve stable

---

## 🧠 Forme conceptuelle

```
reward = (
    α * pnl_normalized
  - β * drawdown
  - γ * trade_frequency
  - δ * volatility
)
```

Où :
- α, β, γ, δ sont des coefficients d’équilibrage

---

## 🛑 Règles fondamentales

- La reward ne doit jamais ignorer le risque
- La reward doit être bornée
- La reward doit être cohérente avec le risk manager

---

## 📌 Conclusion conceptuelle

> La stratégie dit *quoi faire*  
> Le risk manager dit *si c’est autorisé*  
> La reward dit *comment apprendre*

---

✍️ *Ce document complète la phase d’analyse et sert de base à l’implémentation.*

