"""Exception hierarchy for weather bot."""


class WeatherBotError(Exception):
    """Base exception for all weather bot errors."""
    pass


# API Errors
class APIError(WeatherBotError):
    """Base class for API-related errors."""
    pass


class KalshiAPIError(APIError):
    """Kalshi API error."""
    pass


class NWSAPIError(APIError):
    """NWS API error."""
    pass


class RateLimitError(APIError):
    """Rate limit exceeded."""
    pass


class AuthenticationError(KalshiAPIError):
    """Authentication failed."""
    pass


class NetworkError(APIError):
    """Network connectivity error."""
    pass


# Trading Errors
class TradingError(WeatherBotError):
    """Base class for trading-related errors."""
    pass


class InsufficientFunds(TradingError):
    """Insufficient funds for operation."""
    pass


class InvalidOrder(TradingError):
    """Invalid order parameters."""
    pass


class MarketNotFound(TradingError):
    """Market does not exist."""
    pass


class MarketClosed(TradingError):
    """Market is closed for trading."""
    pass


# Strategy Errors
class StrategyError(WeatherBotError):
    """Base class for strategy-related errors."""
    pass


class NoEdgeFound(StrategyError):
    """No trading edge found in current markets."""
    pass


class ForecastError(StrategyError):
    """Error generating or using forecast."""
    pass
