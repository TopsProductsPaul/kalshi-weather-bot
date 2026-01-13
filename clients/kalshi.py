"""Kalshi API client."""

import base64
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .base import BaseClient
from models import Market, Bucket, BucketType, Order, OrderSide, OrderType, OrderStatus, Position
from errors import KalshiAPIError, AuthenticationError, MarketNotFound, InsufficientFunds


PROD_URL = "https://api.elections.kalshi.com"
DEMO_URL = "https://demo-api.kalshi.co"

# Series tickers for crypto markets
CRYPTO_SERIES = {
    "BTC_15M": "KXBTC15M",
    "SOL_DAILY": "KXSOLD",
    "DOGE_DAILY": "KXDOGED",
}

# City codes for weather markets
CITY_CODES = {
    "NYC": "NY",
    "CHICAGO": "CHI",
    "MIAMI": "MIA",
    "AUSTIN": "AUS",
    "DENVER": "DEN",
    "HOUSTON": "HOU",
    "LOS_ANGELES": "LAX",
    "PHILADELPHIA": "PHIL",
}


class KalshiClient(BaseClient):
    """Client for Kalshi prediction market API."""

    def __init__(
        self,
        key_id: str,
        private_key_path: str,
        env: str = "demo",
        verbose: bool = False,
    ):
        base_url = PROD_URL if env == "prod" else DEMO_URL
        super().__init__(base_url=base_url, verbose=verbose)

        self.key_id = key_id
        self.private_key = self._load_private_key(private_key_path)
        self.env = env

    def _load_private_key(self, path: str) -> rsa.RSAPrivateKey:
        """Load RSA private key from PEM file."""
        key_path = Path(path)
        if not key_path.exists():
            raise AuthenticationError(f"Private key not found: {path}")

        with open(key_path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def _sign(self, timestamp: str, method: str, path: str) -> str:
        """Sign request using RSA-PSS."""
        message = f"{timestamp}{method}{path}".encode("utf-8")
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode("utf-8")

    def _auth_headers(self, method: str, path: str) -> dict:
        """Generate authentication headers."""
        timestamp = str(int(time.time() * 1000))
        signature = self._sign(timestamp, method, path)

        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """Authenticated GET request."""
        headers = self._auth_headers("GET", path)
        response = self.get(path, headers=headers, params=params)

        if response.status_code != 200:
            raise KalshiAPIError(f"GET {path} failed: {response.status_code} - {response.text}")

        return response.json()

    def _post(self, path: str, data: Optional[dict] = None) -> dict:
        """Authenticated POST request."""
        headers = self._auth_headers("POST", path)
        response = self.post(path, headers=headers, json=data)

        if response.status_code not in (200, 201):
            if "insufficient" in response.text.lower():
                raise InsufficientFunds(response.text)
            raise KalshiAPIError(f"POST {path} failed: {response.status_code} - {response.text}")

        return response.json()

    def _delete(self, path: str) -> dict:
        """Authenticated DELETE request."""
        headers = self._auth_headers("DELETE", path)
        response = self.delete(path, headers=headers)

        if response.status_code != 200:
            raise KalshiAPIError(f"DELETE {path} failed: {response.status_code} - {response.text}")

        return response.json()

    # Account methods

    def get_balance(self) -> float:
        """Get account balance in dollars."""
        data = self._get("/trade-api/v2/portfolio/balance")
        return data.get("balance", 0) / 100

    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        data = self._get("/trade-api/v2/portfolio/positions", params={"limit": 100})
        positions = []

        for p in data.get("market_positions", []):
            pos = p.get("position", 0)
            if pos == 0:
                continue

            exposure = p.get("market_exposure", 0)
            avg_price = exposure / abs(pos) if pos != 0 else 0

            positions.append(Position(
                ticker=p.get("ticker", ""),
                contracts=pos,
                avg_price=avg_price,
            ))

        return positions

    # Market methods

    def get_weather_events(self, status: str = "open") -> list[dict]:
        """Get weather-related events."""
        data = self._get("/trade-api/v2/events", params={"status": status, "limit": 200})
        events = data.get("events", [])

        weather_keywords = ["temperature", "weather", "rain", "snow", "high", "low"]
        return [
            e for e in events
            if any(kw in e.get("title", "").lower() for kw in weather_keywords)
        ]

    def get_event_markets(self, event_ticker: str) -> list[dict]:
        """Get all markets for an event."""
        data = self._get("/trade-api/v2/markets", params={"event_ticker": event_ticker, "limit": 50})
        return data.get("markets", [])

    def get_market(self, ticker: str) -> dict:
        """Get a single market by ticker."""
        data = self._get(f"/trade-api/v2/markets/{ticker}")
        market = data.get("market")
        if not market:
            raise MarketNotFound(f"Market not found: {ticker}")
        return market

    def get_weather_market(self, city: str, date: datetime, market_type: str = "HIGH") -> Optional[Market]:
        """
        Get a weather market for a specific city and date.

        Args:
            city: City name (e.g., "NYC", "CHICAGO")
            date: Target date
            market_type: "HIGH" or "LOW"

        Returns:
            Market object with buckets, or None if not found
        """
        city_code = CITY_CODES.get(city.upper(), city.upper())
        date_str = date.strftime("%y%b%d").upper()  # e.g., "25JAN02"

        # Try different ticker formats
        event_tickers = [
            f"KX{market_type}{city_code}-{date_str}",
            f"{market_type}{city_code}-{date_str}",
        ]

        for event_ticker in event_tickers:
            try:
                raw_markets = self.get_event_markets(event_ticker)
                if raw_markets:
                    return self._parse_weather_market(event_ticker, city, date, raw_markets)
            except KalshiAPIError:
                continue

        return None

    def _parse_weather_market(
        self,
        event_ticker: str,
        city: str,
        date: datetime,
        raw_markets: list[dict]
    ) -> Market:
        """Parse raw market data into Market object with Buckets."""
        buckets = []

        for m in raw_markets:
            ticker = m.get("ticker", "")
            subtitle = m.get("subtitle", "") or m.get("title", "")

            # Parse bucket type and temperatures from ticker
            # Format: KXHIGHLAX-25DEC30-B70.5 or KXHIGHLAX-25DEC30-T68
            bucket = self._parse_bucket(ticker, m)
            if bucket:
                buckets.append(bucket)

        # Sort buckets by temperature
        buckets.sort(key=lambda b: b.temp_min if b.temp_min else -999)

        return Market(
            event_ticker=event_ticker,
            title=f"{city} temperature on {date.strftime('%Y-%m-%d')}",
            city=city,
            date=date,
            buckets=buckets,
            status="open" if any(m.get("status") == "active" for m in raw_markets) else "closed",
        )

    def _parse_bucket(self, ticker: str, market_data: dict) -> Optional[Bucket]:
        """Parse a single bucket from market data."""
        # Extract bucket indicator from ticker (e.g., "B70.5" or "T68")
        parts = ticker.split("-")
        if len(parts) < 3:
            return None

        bucket_part = parts[-1]  # e.g., "B70.5" or "T68"

        yes_bid = market_data.get("yes_bid") or 0
        yes_ask = market_data.get("yes_ask") or 0
        volume = market_data.get("volume", 0)

        if bucket_part.startswith("B"):
            # Range bucket: B70.5 means 70-71°F
            try:
                midpoint = float(bucket_part[1:])
                temp_min = int(midpoint - 0.5)
                temp_max = int(midpoint + 0.5)
                bucket_type = BucketType.RANGE
            except ValueError:
                return None

        elif bucket_part.startswith("T"):
            # Tail bucket
            try:
                threshold = int(bucket_part[1:])
            except ValueError:
                return None

            # Determine if low or high tail from subtitle
            subtitle = (market_data.get("subtitle") or "").lower()
            if "<" in subtitle or "below" in subtitle:
                bucket_type = BucketType.TAIL_LOW
                temp_min = None
                temp_max = threshold
            else:
                bucket_type = BucketType.TAIL_HIGH
                temp_min = threshold
                temp_max = None
        else:
            return None

        return Bucket(
            ticker=ticker,
            temp_min=temp_min,
            temp_max=temp_max,
            bucket_type=bucket_type,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            volume=volume,
        )

    # Order methods

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        contracts: int,
        price: int,  # In cents (1-99)
        order_type: OrderType = OrderType.LIMIT,
    ) -> Order:
        """
        Place an order.

        Args:
            ticker: Market ticker
            side: BUY or SELL
            contracts: Number of contracts
            price: Price in cents (1-99)
            order_type: LIMIT or MARKET

        Returns:
            Order object
        """
        data = {
            "ticker": ticker,
            "action": "buy" if side == OrderSide.BUY else "sell",
            "side": "yes",  # We always trade YES side
            "count": contracts,
            "type": order_type.value,
        }

        if order_type == OrderType.LIMIT:
            data["yes_price"] = price

        result = self._post("/trade-api/v2/portfolio/orders", data)
        order_data = result.get("order", {})

        return Order(
            id=order_data.get("order_id", ""),
            ticker=ticker,
            side=side,
            order_type=order_type,
            price=price,
            size=contracts,
            filled=order_data.get("filled_count", 0),
            status=self._parse_order_status(order_data.get("status", "")),
            created_at=datetime.now(),
            yes_price=price,
        )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            self._delete(f"/trade-api/v2/portfolio/orders/{order_id}")
            return True
        except KalshiAPIError:
            return False

    def get_open_orders(self) -> list[Order]:
        """Get all open orders."""
        data = self._get("/trade-api/v2/portfolio/orders", params={"status": "resting"})
        orders = []

        for o in data.get("orders", []):
            orders.append(Order(
                id=o.get("order_id", ""),
                ticker=o.get("ticker", ""),
                side=OrderSide.BUY if o.get("action") == "buy" else OrderSide.SELL,
                order_type=OrderType.LIMIT if o.get("type") == "limit" else OrderType.MARKET,
                price=o.get("yes_price", 0),
                size=o.get("remaining_count", 0) + o.get("filled_count", 0),
                filled=o.get("filled_count", 0),
                status=self._parse_order_status(o.get("status", "")),
            ))

        return orders

    def _parse_order_status(self, status: str) -> OrderStatus:
        """Parse order status string to enum."""
        status_map = {
            "resting": OrderStatus.OPEN,
            "pending": OrderStatus.PENDING,
            "executed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
        }
        return status_map.get(status.lower(), OrderStatus.PENDING)

    # Crypto market methods

    def get_btc_15m_markets(self, status: str = None) -> list[dict]:
        """
        Get BTC 15-minute up/down markets.

        Args:
            status: Market status filter (None for all, or specific status)

        Returns:
            List of market dicts with ticker, close_time, yes_bid, yes_ask, etc.
        """
        params = {"series_ticker": CRYPTO_SERIES["BTC_15M"], "limit": 100}
        if status:
            params["status"] = status

        try:
            data = self._get("/trade-api/v2/markets", params=params)
            return data.get("markets", [])
        except Exception:
            # Fallback without status filter
            try:
                data = self._get(
                    "/trade-api/v2/markets",
                    params={"series_ticker": CRYPTO_SERIES["BTC_15M"], "limit": 100}
                )
                return data.get("markets", [])
            except Exception:
                return []

    def get_active_btc_market(self) -> Optional[dict]:
        """
        Get the currently active BTC 15-minute market.

        Returns:
            Market dict if there's an active market, None otherwise.
        """
        # Get open markets
        markets = self.get_btc_15m_markets(status="open")
        for m in markets:
            yes_bid = m.get("yes_bid") or 0
            yes_ask = m.get("yes_ask") or 100
            # Market has liquidity if there's a spread
            if yes_bid > 0 or yes_ask < 100:
                return m

        # Also try without status filter (gets all)
        try:
            data = self._get(
                "/trade-api/v2/markets",
                params={"series_ticker": CRYPTO_SERIES["BTC_15M"], "limit": 20}
            )
            markets = data.get("markets", [])
            for m in markets:
                if m.get("status") == "open":
                    yes_bid = m.get("yes_bid") or 0
                    yes_ask = m.get("yes_ask") or 100
                    if yes_bid > 0 or yes_ask < 100:
                        return m
        except Exception:
            pass

        return None

    def get_crypto_markets(self, series: str, status: str = "open") -> list[dict]:
        """
        Get markets for a crypto series.

        Args:
            series: Series key from CRYPTO_SERIES (e.g., "BTC_15M", "SOL_DAILY")
            status: Market status filter

        Returns:
            List of market dicts
        """
        series_ticker = CRYPTO_SERIES.get(series, series)
        data = self._get(
            "/trade-api/v2/markets",
            params={"series_ticker": series_ticker, "status": status, "limit": 100}
        )
        return data.get("markets", [])
