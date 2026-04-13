# TradePy 90-Minute Auto-Close Feature Implementation

## Overview
This implementation adds an automatic trade closing mechanism that closes trades after 90 minutes to prevent long sessions that could expose the bot to changing market trends.

## Key Components

### 1. AutoCloseScheduler Class (`core/trading/auto_close_scheduler.py`)
- Monitors open trades and tracks their opening time
- Automatically closes trades that have been open for more than 90 minutes
- Integrates with the existing `close_position` method
- Provides methods to register/unregister trades and check for expired ones

### 2. Integration with LiveRunner (`live/runner.py`)
- Initialized AutoCloseScheduler with 90-minute timeout
- Registers trades when they are opened
- Unregisters trades when they are closed manually or reach targets
- Checks for and closes expired trades in the main loop

## How It Works

1. When a trade is opened, it gets registered with the AutoCloseScheduler
2. Every cycle in the main loop, the scheduler checks for trades that have exceeded the 90-minute limit
3. Expired trades are automatically closed using the existing `close_position` method
4. Successfully closed trades are unregistered from the scheduler

## Benefits

- Prevents long trading sessions that could be exposed to changing market trends
- Reduces risk from holding positions too long
- Maintains the existing risk management infrastructure
- Works with both simulated and live trading environments

## Configuration

The timeout can be adjusted by changing the `timeout_minutes` parameter when initializing the AutoCloseScheduler (currently set to 90 minutes as requested).

## Testing

- Comprehensive unit tests for the AutoCloseScheduler functionality
- Verified integration with existing LiveRunner tests
- Demo script showing the functionality in action