"""Trading strategies."""

from .base import Strategy
from .weather_bot import WeatherBotStrategy, run_weather_bot
from .btc_bot import BTCBotStrategy, run_btc_bot
from .btc_hedged import BTCHedgedStrategy, run_btc_hedged
from .spread_selector import select_spread, find_peak_bucket, find_best_neighbor

__all__ = [
    "Strategy",
    "WeatherBotStrategy",
    "run_weather_bot",
    "BTCBotStrategy",
    "run_btc_bot",
    "BTCHedgedStrategy",
    "run_btc_hedged",
    "select_spread",
    "find_peak_bucket",
    "find_best_neighbor",
]
