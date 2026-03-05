"""
Configuration settings
"""
from typing import Dict, List, Optional, Union
import yaml
from pydantic import BaseModel, Field, ValidationError, validator


class TradingConfig(BaseModel):
    class Config:
        extra = "allow"

    use_mt5: bool = False
    dry_run: bool = True
    timeframe: int = Field(default=5, ge=1)
    timeframes: Optional[List[Union[int, str]]] = None
    preferred_timeframe: Optional[Union[int, str]] = None
    poll_seconds: int = Field(default=5, ge=1, le=3600)


class StrategyConfig(BaseModel):
    class Config:
        extra = "allow"

    sl_atr_multiplier: float = Field(default=2.0, gt=0)
    tp_atr_multiplier: float = Field(default=3.0, gt=0)
    sl_tp_overrides_by_symbol: Dict[str, Dict[str, float]] = Field(default_factory=dict)


class RiskConfig(BaseModel):
    class Config:
        extra = "allow"

    max_daily_loss_pct: float = Field(default=0.03, ge=0, le=1)
    max_consecutive_losses: int = Field(default=3, ge=0)
    max_trades_per_day: int = Field(default=10, ge=0)
    max_open_trades_per_symbol: int = Field(default=1, ge=0)
    max_global_open_positions: Optional[int] = Field(default=None, ge=0)
    cooldown_minutes_after_loss: int = Field(default=45, ge=0)
    global_cooldown_minutes_after_loss: int = Field(default=0, ge=0)
    no_trade_after_hour: Optional[int] = Field(default=None, ge=0, le=23)
    state_path: str = "runtime/state.json"
    max_spread_points: Optional[float] = Field(default=None, ge=0)
    max_slippage_points: Optional[float] = Field(default=None, ge=0)


class AppConfig(BaseModel):
    class Config:
        extra = "allow"

    initial_capital: float = Field(default=10000, gt=0)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    symbol_schedule: Dict[int, List[str]] = Field(default_factory=dict)

    @validator("symbol_schedule", pre=True)
    def validate_symbol_schedule(cls, value):
        validated = {}
        for raw_day, symbols in (value or {}).items():
            day = int(raw_day)
            if day < 0 or day > 6:
                raise ValueError("symbol_schedule keys must be between 0 and 6")
            if not isinstance(symbols, list):
                raise ValueError("symbol_schedule values must be lists of symbols")
            cleaned = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
            validated[day] = cleaned
        return validated


def load_config(config_path: str):
    """Load and validate configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file) or {}

    if not isinstance(raw_config, dict):
        raise ValueError(f"Configuration root must be a mapping: {config_path}")

    try:
        if hasattr(AppConfig, "model_validate"):
            validated = AppConfig.model_validate(raw_config)
        else:
            validated = AppConfig.parse_obj(raw_config)
    except ValidationError as exc:
        raise ValueError(f"Invalid configuration in {config_path}: {exc}") from exc

    if hasattr(validated, "model_dump"):
        return validated.model_dump()
    return validated.dict()
