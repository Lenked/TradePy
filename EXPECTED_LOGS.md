# Expected Logs Examples

## When trading.use_mt5: true (LIVE_MT5 Mode)

### Startup Check:
```
============================================================
STARTUP CHECK PASSED
Mode: LIVE_MT5
Exchange: MT5Executor
Login: ***XXXX  (last 4 digits of MT5 login)
Server: Exness-MT5Trial5  (or your real server)
Account Type: DEMO/REAL
============================================================
Connected to Demo/Simulated Exchange
Mode: LIVE_MT5
```

### When order is placed:
```
MT5_ORDER_SENT - Ticket: 12345678 - BUY 0.1 EURUSD | SL: 1.0500 | TP: 1.0700
```

### Error case (if login fails):
```
ERROR - Failed to connect to MT5: Login failed
ERROR - Missing MT5 credentials. Please set MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER in your environment.
ERROR - Cannot proceed with LIVE_MT5 mode without credentials.
```

## When trading.use_mt5: false (SIMULATION Mode)

### Startup Check:
```
============================================================
STARTUP CHECK PASSED
Mode: SIMULATION
Exchange: SimulatedBroker
============================================================
Connected to Demo/Simulated Exchange
Mode: SIMULATION
```

### When order is placed with dry_run=true:
```
DRY_RUN_ORDER_SIMULATED - BUY 0.1 EURUSD | SL: 1.0500 | TP: 1.0700
```

### When order is placed in simulation mode (dry_run=false but use_mt5=false):
```
SIM_ORDER_SENT - BUY 0.1 EURUSD | SL: 1.0500 | TP: 1.0700
```

## Key Differences:
- LIVE_MT5 mode: Uses MT5_ORDER_SENT with ticket numbers and MT5-specific retcodes
- SIMULATION mode: Uses SIM_ORDER_SENT (NOT "REAL_ORDER_SENT")
- LIVE_MT5 mode: Shows MT5 credentials in startup check
- SIMULATION mode: No credential requirements shown