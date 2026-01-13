"""Trading strategies."""

from .base import Strategy
from .weather_bot import WeatherBotStrategy, run_weather_bot
from .spread_selector import select_spread, find_peak_bucket, find_best_neighbor

__all__ = [
    "Strategy",
    "WeatherBotStrategy",
    "run_weather_bot",
    "select_spread",
    "find_peak_bucket",
    "find_best_neighbor",
]
