"""Crypto price client using free APIs."""

import time
from typing import Optional
from datetime import datetime, timezone

from .base import BaseClient


class CryptoClient(BaseClient):
    """
    Client for fetching cryptocurrency prices.
    Uses CoinGecko (free, no API key required).
    """

    def __init__(self, verbose: bool = False):
        super().__init__(base_url="https://api.coingecko.com", verbose=verbose)
        self._price_cache: dict[str, tuple[float, float]] = {}  # symbol -> (price, timestamp)
        self._cache_ttl = 5  # seconds

    def get_btc_price(self) -> float:
        """Get current BTC price in USD."""
        return self._get_price("bitcoin")

    def get_eth_price(self) -> float:
        """Get current ETH price in USD."""
        return self._get_price("ethereum")

    def get_sol_price(self) -> float:
        """Get current SOL price in USD."""
        return self._get_price("solana")

    def _get_price(self, coin_id: str) -> float:
        """Get current price for a coin, with caching."""
        now = time.time()

        # Check cache
        if coin_id in self._price_cache:
            cached_price, cached_time = self._price_cache[coin_id]
            if now - cached_time < self._cache_ttl:
                return cached_price

        # Fetch fresh price
        try:
            response = self.get(
                "/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd"}
            )

            if response.status_code == 200:
                data = response.json()
                price = data.get(coin_id, {}).get("usd", 0.0)
                self._price_cache[coin_id] = (price, now)
                return price
        except Exception as e:
            if self.verbose:
                print(f"Error fetching {coin_id} price: {e}")

        # Return cached price if available, even if stale
        if coin_id in self._price_cache:
            return self._price_cache[coin_id][0]

        return 0.0


class BinanceClient(BaseClient):
    """
    Alternative client using Binance API (faster, more reliable for trading).
    No API key needed for public price endpoints.
    Uses Binance US endpoint for US users.
    """

    def __init__(self, verbose: bool = False, use_us: bool = True):
        # Use Binance US for US-based users (more reliable)
        base_url = "https://api.binance.us" if use_us else "https://api.binance.com"
        super().__init__(base_url=base_url, verbose=verbose)
        self._use_us = use_us

    def get_btc_price(self) -> float:
        """Get current BTC/USDT price."""
        return self._get_price("BTCUSDT")

    def get_eth_price(self) -> float:
        """Get current ETH/USDT price."""
        return self._get_price("ETHUSDT")

    def get_sol_price(self) -> float:
        """Get current SOL/USDT price."""
        return self._get_price("SOLUSDT")

    def _get_price(self, symbol: str) -> float:
        """Get current price for a trading pair."""
        try:
            response = self.get(
                "/api/v3/ticker/price",
                params={"symbol": symbol}
            )

            if response.status_code == 200:
                data = response.json()
                return float(data.get("price", 0))
        except Exception as e:
            if self.verbose:
                print(f"Error fetching {symbol} price: {e}")

        return 0.0

    def get_price_at_time(self, symbol: str, timestamp_ms: int) -> Optional[float]:
        """
        Get price at a specific timestamp using klines.
        Useful for determining start-of-window price.
        """
        try:
            response = self.get(
                "/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": "1m",
                    "startTime": timestamp_ms,
                    "limit": 1
                }
            )

            if response.status_code == 200:
                data = response.json()
                if data:
                    # Kline format: [open_time, open, high, low, close, ...]
                    return float(data[0][1])  # Open price
        except Exception as e:
            if self.verbose:
                print(f"Error fetching historical price: {e}")

        return None
