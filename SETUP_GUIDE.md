# TradePy Development Environment Setup Guide

This guide explains how to properly set up the development environment for TradePy.

## Requirements

Before installing TradePy, ensure you have:
- Python 3.8 or higher
- pip package manager
- Internet connection for downloading dependencies

## Recommended Setup Process

### Option 1: Using Anaconda/Miniconda (Recommended for Windows)

1. Install Anaconda or Miniconda
2. Create a new environment:
```bash
conda create -n tradepy python=3.9
conda activate tradepy
```

3. Install required packages:
```bash
conda install pandas numpy matplotlib seaborn scipy scikit-learn pyyaml
```

4. Install the package in development mode:
```bash
pip install -e .
```

### Option 2: Using Virtual Environment with Pre-compiled Wheels

1. Create a virtual environment:
```bash
python -m venv tradepy_env
tradepy_env\Scripts\activate  # On Windows
# source tradepy_env/bin/activate  # On Linux/Mac
```

2. Upgrade pip:
```bash
python -m pip install --upgrade pip
```

3. Install packages using pre-compiled wheels:
```bash
pip install --only-binary=all pandas numpy matplotlib seaborn scipy scikit-learn pyyaml
```

4. Install TradePy in development mode:
```bash
pip install -e .
```

### Option 3: Using Docker (Alternative)

If you continue to face installation issues, consider using Docker:

1. Install Docker Desktop
2. Create a Dockerfile:
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install -e .

CMD ["python", "validate_framework.py"]
```

3. Build and run:
```bash
docker build -t tradepy .
docker run tradepy
```

## Architecture Validation

The framework is structured according to clean architecture principles:

```
TradePy/
├── config/
│   ├── settings.yaml
│   ├── risk.yaml
│   └── assets.yaml
├── data/
│   ├── raw/
│   ├── processed/
│   └── features/
├── core/
│   ├── exchange/
│   ├── indicators/
│   ├── strategy/
│   ├── portfolio/
│   ├── risk/
│   └── execution/
├── backtest/
│   ├── engine.py
│   ├── analysis.py
│   ├── benchmark.py
│   ├── walk_forward.py
│   ├── metrics.py
│   └── reports.py
├── ai/
├── live/
├── utils/
├── tests/
├── main.py
└── validate_framework.py
```

## Key Components Implemented

### Core Components
- **Data Validation**: `core/data/validator.py` - Prevents look-ahead bias
- **Risk Management**: `core/validation/risk_validation.py` - Implements risk checks
- **Kill Switch**: `live/kill_switch.py` - Emergency shutdown system
- **Strategy**: `core/strategy/trend_following_strategy.py` - Baseline strategy

### Backtesting Components  
- **Analysis**: `backtest/analysis.py` - Performance metrics
- **Benchmark**: `backtest/benchmark.py` - Strategy comparison
- **Walk-Forward**: `backtest/walk_forward.py` - Robustness validation

### Validation Script
- **`validate_framework.py`** - Complete pipeline validation

## Manual Architecture Verification

If you cannot run the automated validation, you can manually verify:

1. **File existence and imports**: All required modules exist
2. **Class structures**: Proper inheritance and interfaces
3. **Documentation**: Clear docstrings and comments
4. **Responsibility separation**: Each module has a single clear responsibility

## Running the Validation Script

Once your environment is set up:
```bash
python validate_framework.py
```

This will execute:
1. Data generation and validation
2. Basic backtesting
3. Benchmark comparison
4. Walk-forward analysis
5. Complete framework validation

## Troubleshooting

- If you encounter compilation errors, ensure Visual Studio Build Tools are installed (for Windows)
- Check that your Python version meets the minimum requirements
- Verify you have sufficient disk space and permissions

## Philosophy

Remember the core philosophy: "A bot that survives long with modest gains is a success. A bot that aims for high gains but risks dying is a failure."

This framework implements that philosophy through:
- Strict data validation
- Mandatory risk management
- Emergency kill switches
- Robustness testing
- Realistic performance expectations