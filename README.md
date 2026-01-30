# TradePy - AI Trading Bot Framework

TradePy is a robust, well-architected trading bot framework designed with clean architecture principles, prioritizing system survival over aggressive profit-seeking.

## Philosophy

> "A bot that survives long with modest gains is a success. A bot that aims for high gains but risks dying is a failure."

This framework implements that philosophy through:
- Strict data validation to prevent lookahead bias
- Mandatory risk management
- Emergency kill switches
- Robustness validation via walk-forward analysis
- Clean separation of concerns

## Project Structure

```
TradePy/
├── config/                 # Configuration files
│   ├── settings.yaml       # General settings
│   ├── risk.yaml          # Risk management rules
│   └── assets.yaml        # Traded assets
├── data/                  # Data management
│   ├── raw/               # Raw market data
│   ├── processed/         # Processed data
│   └── features/          # Feature-engineered data
├── core/                  # Core trading logic
│   ├── exchange/          # Exchange interfaces
│   ├── indicators/        # Technical indicators
│   ├── strategy/          # Trading strategies
│   ├── portfolio/         # Portfolio management
│   ├── risk/              # Risk management
│   └── execution/         # Order execution
├── backtest/              # Backtesting components
│   ├── engine.py          # Backtest engine
│   ├── analysis.py        # Analysis tools
│   ├── benchmark.py       # Benchmarking
│   ├── walk_forward.py    # Walk-forward analysis
│   └── reports.py         # Reports generation
├── ai/                    # AI/ML components (optional)
├── live/                  # Live trading components
│   ├── runner.py          # Live trading runner
│   ├── watcher.py         # Risk monitoring
│   ├── notifier.py        # Notifications
│   └── kill_switch.py     # Emergency controls
├── utils/                 # Utility functions
├── tests/                 # Unit and integration tests
├── main.py                # Main entry point
└── README.md              # This file
```

## Architecture Principles

### 1. Data Flow
```
Data → Features → Strategy → Risk → Portfolio → Execution
                            ↓
                         AI / RL
```

### 2. Key Modules

#### Core Components
- **Data Validator**: Prevents lookahead bias and ensures data integrity
- **Risk Validators**: Check maximum drawdown, risk per trade, position size
- **Kill Switch**: Emergency shutdown when critical thresholds are breached
- **Strategy Interface**: Common interface for rule-based and AI strategies

#### Backtesting Components
- **Backtest Engine**: Runs historical simulations
- **Analysis Module**: Calculates performance metrics
- **Benchmark Module**: Compares against baseline strategies
- **Walk-Forward Analyzer**: Tests robustness across time periods

## Installation & Setup

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Quick Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd TradePy
```

2. Create virtual environment:
```bash
python -m venv tradepy_env
source tradepy_env/bin/activate  # On Linux/Mac
tradepy_env\Scripts\activate    # On Windows
```

3. Install dependencies:
```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### Alternative Setup (for Windows compatibility)
If you encounter issues with binary compilation, use:
```bash
pip install --only-binary=all pandas numpy matplotlib seaborn scipy scikit-learn pyyaml
pip install -e .
```

## Validation Scripts

### 1. Syntax Validation
Verify all Python files have correct syntax:
```bash
python validate_syntax.py
```

### 2. Structural Validation
Check that all required modules exist:
```bash
python validate_structure_only.py
```

## Execution Examples

### Basic Backtest
```bash
python main.py --mode backtest
```

### Paper Trading
```bash
python main.py --mode paper
```

### Live Trading
```bash
python main.py --mode live
```

## How to run experiments

### MT5 Experiments
Run experimental trading bots from the experiments directory:

```bash
python experiments/mt5/weekend_btc_trading_bot.py
```

All experiment logs are stored in `artifacts/logs/`.

## How to run live trading

### Live Runner (Single Entry Point)
The live runner is the single entry point for live trading execution:

```bash
# First, copy .env.example to .env and add your MT5 credentials
copy .env.example .env  # On Windows
# cp .env.example .env  # On Linux/Mac
# Then edit .env with your actual credentials

# Run live trading with the live runner (auto-symbol selection by day of week)
python experiments/mt5/live_runner_example.py
```

The live runner supports automatic symbol selection based on the day of the week:
- Saturday + Sunday: ["BTCUSDm"]
- Monday to Friday: ["BTCUSDm", "XAUUSDm", "EURUSDm", "USOILm", "NVDAm"]

The live runner takes a strategy, exchange (MT5Executor), risk_manager, and kill_switch to execute trades in real-time.

### Run MT5 Exness
Safe by default: TradePy will not send real orders unless you explicitly accept live risk.

```bash
# 1) Copy and configure credentials
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/Mac

# 2) Dry-run with MT5 (no real orders sent)
python main.py --mode live --config config/settings.yaml

# 3) Real MT5 orders (requires explicit acknowledgement)
python main.py --mode live --config config/settings.yaml --i-accept-live-risk
```

Notes:
- `config/settings.yaml` controls `trading.use_mt5` and `trading.dry_run`.
- MT5 dry-run logs: `MT5_DRY_RUN_ORDER_SIMULATED`
- MT5 live logs: `MT5_ORDER_SENT`
- Simulation logs: `SIM_ORDER_SENT`

### Setting up your own strategy
To use your own trading strategy with the live runner, implement the following interface:

- `strategy.generate_signal(df)` - Generate a trading signal (BUY/SELL/HOLD) based on market data
- `strategy.compute_sl_tp(df, signal)` - Calculate stop loss and take profit levels
- `strategy.compute_volume(df, signal, equity)` - Calculate position size based on equity
- `risk_manager.allow_trade(signal, sl, tp, account_snapshot)` - Check if trade meets risk criteria
- `kill_switch.evaluate(metrics)` - Evaluate kill switch conditions and return dict with "triggered" key

### Auto-symbol selection
To enable auto-symbol selection, initialize the LiveRunner with `symbol="AUTO"`. The system will automatically select the appropriate symbol based on the current day of the week according to the schedule defined in `core/utils/symbol_schedule.py`. When switching symbols, the system will not close existing positions but will wait for them to close before opening new positions on the new symbol.

## Core Features

### 1. Risk Management
- Maximum drawdown limits
- Risk per trade controls
- Position size restrictions
- Automatic kill switches

### 2. Validation Components
- Data validation to prevent lookahead bias
- Walk-forward analysis for robustness testing
- Benchmark comparisons
- Performance metrics reporting

### 3. Monitoring & Control
- Real-time risk monitoring
- Automated kill switches
- Notification system
- Detailed logging

## Development Guidelines

### Code Organization
- Each module has a single responsibility
- All business logic is contained in `core/`
- Infrastructure concerns are separate
- Dependencies flow inward only

### Testing Strategy
1. Unit tests for individual components
2. Integration tests for workflows
3. Walk-forward analysis for robustness
4. Live testing with paper trading

## Roadmap

### Phase 1 - Foundation (Complete)
- [x] Data validation
- [x] Basic risk management
- [x] Backtesting engine
- [x] Kill switch implementation
- [x] Walk-forward analysis

### Phase 2 - Robustness (Planned)
- [ ] Advanced risk controls
- [ ] Multiple benchmark strategies
- [ ] Stress testing framework
- [ ] Improved error handling

### Phase 3 - AI Enhancement (Future)
- [ ] Reinforcement learning integration
- [ ] Advanced reward functions
- [ ] Model validation framework

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add your changes with proper tests
4. Submit a pull request

## License

MIT License - See LICENSE file for details.

## Disclaimer

This software is for educational and research purposes only. Trading involves substantial risk of loss. Past performance does not guarantee future results. Use at your own risk.

Remember: The goal is survival, not maximum profit.
