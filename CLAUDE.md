# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is TradePy

TradePy is an algorithmic trading bot that trades Forex/CFD instruments (BTCUSDm, XAUUSDm, USOILm, EURUSDm, NVDAm) via MetaTrader 5 on Exness. It combines a trend-following strategy with a hybrid AI decision engine and an ML-based trade guard. The project philosophy is **survival over profit** — strict risk management is more important than aggressive gains.

## Commands

```bash
# Install
pip install -r requirements.txt
pip install -e .

# Run tests
pytest
pytest tests/test_risk_manager_guards.py          # single file
pytest tests/test_risk_manager_guards.py::test_name  # single test
pytest -x                                          # stop on first failure

# Run the bot
python main.py --mode backtest
python main.py --mode paper
python main.py --mode live --config config/settings.yaml                        # dry-run (no real orders)
python main.py --mode live --config config/settings.yaml --i-accept-live-risk   # real orders

# Run example bots
python examples/mt5/live_runner_example.py
python examples/mt5/weekend_btc_trading_bot.py

# AI model training pipeline
python -m ai.training.dashboard_dataset_builder   # Phase A: build dataset from data/dashboard.json
python -m ai.training.dashboard_model_trainer      # Phase B: train model → artifacts/models/dashboard_decision_model_bundle.joblib
```

MT5 credentials are read from `.env` (copy `.env.example` and fill in `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`). Log level is controlled by `LOG_LEVEL` env var.

## Architecture

### Layer model

```
live/               Orchestration — LiveRunner main loop, kill switch, notifications
  ↓ depends on
core/               Domain logic — strategy, risk, execution, portfolio (pure, no external deps)
  ↓ implements
core/exchange/      Interfaces — LiveExchangeInterface, BacktestDataInterface
  ↓ implemented by
core/execution/     Infrastructure — MT5Executor, SimulatedBroker
```

Dependencies flow inward only: `live/` depends on `core/` interfaces, never on concrete implementations. `core/` has no knowledge of `live/` or `backtest/`.

### Key interfaces

- **`Strategy`** (`core/strategy/base.py`): `generate_signal(df)`, `compute_sl_tp(df, signal)`, `compute_volume(df, signal, equity)`
- **`LiveExchangeInterface`** (`core/exchange/live_interface.py`): `connect()`, `get_rates()`, `place_market_order()`, `close_position()`, `update_position_protection()`, `account_info()`, `positions()`, `floating_pnl()`
- **`RiskManager`** (`core/risk/manager.py`): `allow_trade()` — the single gatekeeper before any order

### Trading flow (every 5 seconds)

1. `LiveRunner.run()` polls MT5 for new bars across configured timeframes (5/15/60 min)
2. `TrendFollowingStrategy.generate_signal()` computes EMA50/200, RSI14, ATR14, MACD
3. `HybridDecisionEngine` scores 5 weighted features (trend, momentum, alignment, breakout, volatility) — can confirm or override the base signal
4. `RiskManager.allow_trade()` checks daily loss limits, position limits, cooldowns, spread/slippage, session windows
5. `DashboardDecisionGuard` predicts P(big_loss) using a pre-trained ML model — blocks or throttles if above threshold
6. `MT5Executor.place_market_order()` sends the order (SL and TP are mandatory)
7. `AutoCloseScheduler` registers the trade for 90-minute timeout
8. `SignalSnapshotStore` logs the decision to `runtime/ai_signal_snapshots.jsonl`

### AI decision system (`ai/`)

Three-phase pipeline:
- **Phase A** (`ai/training/dashboard_dataset_builder.py`): Builds features from `data/dashboard.json` — rolling stats over 5/10/20/50 trade windows (win rate, drawdown, per-symbol/per-side performance)
- **Phase B** (`ai/training/dashboard_model_trainer.py`): Trains a `HistGradientBoostingClassifier` and saves to `artifacts/models/dashboard_decision_model_bundle.joblib`
- **Phase C** (`ai/decision/dashboard_guard.py`): `DashboardDecisionGuard` loads the model at runtime, `TradeRegimeTracker` maintains live performance stats, predicts on each trade candidate. Modes: `shadow` (log only) or `enforce` (block/throttle)

### Risk management (`core/risk/manager.py`)

Six layers, all configured in `config/settings.yaml` under `risk:`:
1. Daily limits (2% or $60 max loss, 8 trades/day, per-symbol caps)
2. Position limits (1 per symbol, 2 global)
3. Cooldowns (per-symbol and global after loss)
4. Spread/slippage guards (per-symbol thresholds)
5. AI filters (dashboard guard blocks high-risk trades)
6. Kill switch + auto-close after 90 min

### State and persistence

No database — all state is file-based:
- `runtime/state.json` — risk manager runtime state (daily PnL, trade counts, cooldowns)
- `runtime/ai_signal_snapshots.jsonl` — all AI decision events
- `reports/trade_history.jsonl` / `.csv` — closed trade records
- `data/dashboard.json` — historical MT5 data used for AI training

## Configuration

All in `config/settings.yaml`. Three main sections:
- `trading:` — MT5 connection, timeframes, poll interval
- `strategy:` — indicator params, AI decision config, scalping config, intra-bar trading, SL/TP overrides by symbol
- `risk:` — all risk limits, cooldowns, position sizing, trading sessions by symbol/timezone

Symbol schedule for AUTO mode is in `symbol_schedule:` — maps day-of-week to tradeable symbols.

## Conventions

- Logging uses `utils.logger.Logger` / `RateLimitedLogger` — no `print()` in business logic
- All market orders require SL and TP (safe-by-default)
- Config is loaded via `config.config.load_config()` returning a plain dict from YAML
- Shared dataclasses live in `core/models.py`: `AccountSnapshot`, `OrderRequest`, `OrderResult`, `SymbolTradeConstraints`, `TradeState`
- Comments in config files are in French (the developer's language)
