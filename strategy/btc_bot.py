"""BTC 15-minute price prediction bot strategy."""

from datetime import datetime, timezone, timedelta
from typing import Optional
import re

from .base import Strategy
from clients import KalshiClient
from clients.crypto import BinanceClient
from models import OrderSide, OrderType


class BTCBotStrategy(Strategy):
    """
    BTC 15-minute up/down trading strategy.

    Monitors KXBTC15M markets and bets when:
    1. Market is near close (last N minutes of window)
    2. BTC price has clearly moved in one direction
    3. The outcome is nearly certain

    Example: If BTC started at $95,000 and is now $95,500 with 2 minutes left,
    bet YES on "BTC up in next 15 mins" at whatever price is available.
    """

    def __init__(
        self,
        kalshi: KalshiClient,
        min_confidence: float = 0.80,  # Minimum confidence to bet (0-1)
        max_minutes_before_close: int = 3,  # Only bet in last N minutes
        min_price_change_pct: float = 0.1,  # Min % change to consider "certain"
        contracts_per_bet: int = 10,
        max_price: int = 95,  # Don't pay more than 95¢
        **kwargs,
    ):
        super().__init__(kalshi=kalshi, **kwargs)

        self.min_confidence = min_confidence
        self.max_minutes_before_close = max_minutes_before_close
        self.min_price_change_pct = min_price_change_pct
        self.contracts_per_bet = contracts_per_bet
        self.max_price = max_price

        # Crypto price client
        self.crypto = BinanceClient(verbose=kwargs.get("verbose", False))

        # Track what we've traded
        self._traded_markets: set[str] = set()
        self._window_start_prices: dict[str, float] = {}

    def setup(self):
        """Initialize strategy."""
        self.log("BTC 15M Bot initialized")
        self.log(f"Min confidence: {self.min_confidence:.0%}")
        self.log(f"Bet window: last {self.max_minutes_before_close} minutes")
        self.log(f"Min price change: {self.min_price_change_pct}%")
        self.log(f"Max price: {self.max_price}¢")
        self.log(f"Contracts per bet: {self.contracts_per_bet}")
        self.log(f"Dry run: {self.dry_run}")

    def on_start(self):
        """Log starting status."""
        self.log_status()

        # Test crypto connection
        btc_price = self.crypto.get_btc_price()
        if btc_price > 0:
            self.log(f"Current BTC price: ${btc_price:,.2f}")
        else:
            self.log("Warning: Could not fetch BTC price")

    def on_tick(self):
        """Main trading logic - check for opportunities."""
        try:
            self._check_btc_markets()
        except Exception as e:
            self.log(f"Error in on_tick: {e}")

    def on_stop(self):
        """Log final status."""
        self.log("BTC Bot stopping")
        self.log_status()
        self.log(f"Markets traded: {len(self._traded_markets)}")

    def _check_btc_markets(self):
        """Check BTC 15M markets for opportunities."""
        # Get active market
        market = self.kalshi.get_active_btc_market()

        if not market:
            self.log("No active BTC 15M market found")
            return

        ticker = market.get("ticker", "")
        if ticker in self._traded_markets:
            return  # Already traded this window

        # Parse window timing
        window_info = self._parse_window(ticker, market)
        if not window_info:
            self.log(f"Could not parse window for {ticker}")
            return

        start_time, end_time, minutes_left = window_info

        # Only trade in the final minutes
        if minutes_left > self.max_minutes_before_close:
            self.log(f"{ticker}: {minutes_left:.1f} min left (waiting for last {self.max_minutes_before_close} min)")
            return

        # Get prices
        start_price = self._get_window_start_price(ticker, start_time)
        current_price = self.crypto.get_btc_price()

        if start_price <= 0 or current_price <= 0:
            self.log("Could not get BTC prices")
            return

        # Calculate price change
        price_change_pct = ((current_price - start_price) / start_price) * 100
        is_up = price_change_pct > 0

        self.log(f"{ticker}: BTC ${start_price:,.0f} → ${current_price:,.0f} ({price_change_pct:+.2f}%)")
        self.log(f"  Minutes left: {minutes_left:.1f}, Direction: {'UP' if is_up else 'DOWN'}")

        # Check if outcome is nearly certain
        if abs(price_change_pct) < self.min_price_change_pct:
            self.log(f"  Price change too small ({abs(price_change_pct):.2f}% < {self.min_price_change_pct}%)")
            return

        # Determine bet
        # "BTC up in next 15 mins" = YES means price went up
        should_bet_yes = is_up
        yes_bid = market.get("yes_bid") or 0
        yes_ask = market.get("yes_ask") or 100

        self.log(f"  Market: YES {yes_bid}/{yes_ask}¢")

        # Calculate our confidence based on price movement and time left
        confidence = self._calculate_confidence(price_change_pct, minutes_left)
        self.log(f"  Confidence: {confidence:.0%}")

        if confidence < self.min_confidence:
            self.log(f"  Confidence too low ({confidence:.0%} < {self.min_confidence:.0%})")
            return

        # Place bet
        if should_bet_yes:
            # Buy YES - use the ask price (what we pay to buy)
            price = yes_ask
            if price > self.max_price:
                self.log(f"  YES ask too high ({price}¢ > {self.max_price}¢)")
                return

            self._place_bet(ticker, "yes", price)
        else:
            # Buy NO - equivalent to selling YES at bid
            # Actually, easier to buy NO which means bet on price going down
            # NO price = 100 - YES price
            no_price = 100 - yes_bid if yes_bid > 0 else 100

            if no_price > self.max_price:
                self.log(f"  NO price too high ({no_price}¢ > {self.max_price}¢)")
                return

            # On Kalshi, to bet NO we sell YES
            # But if there's no bid, we can't sell
            if yes_bid <= 0:
                self.log("  No bid to sell YES (bet NO)")
                return

            self._place_bet(ticker, "no", yes_bid)

        self._traded_markets.add(ticker)

    def _parse_window(self, ticker: str, market: dict) -> Optional[tuple[datetime, datetime, float]]:
        """
        Parse window start/end times from ticker and market data.

        Ticker format: KXBTC15M-26JAN132315-15
        - 26JAN13 = Jan 13, 2026
        - 2315 = 23:15 UTC
        - -15 = ends at :15 (every 15 min interval)

        Returns:
            (start_time, end_time, minutes_left) or None
        """
        close_time_str = market.get("close_time") or market.get("expiration_time")
        if not close_time_str:
            return None

        try:
            end_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            start_time = end_time - timedelta(minutes=15)

            now = datetime.now(timezone.utc)
            minutes_left = (end_time - now).total_seconds() / 60

            return (start_time, end_time, minutes_left)
        except Exception:
            return None

    def _get_window_start_price(self, ticker: str, start_time: datetime) -> float:
        """Get BTC price at window start, with caching."""
        if ticker in self._window_start_prices:
            return self._window_start_prices[ticker]

        # Use Binance klines to get historical price
        timestamp_ms = int(start_time.timestamp() * 1000)
        price = self.crypto.get_price_at_time("BTCUSDT", timestamp_ms)

        if price:
            self._window_start_prices[ticker] = price
            return price

        # Fallback: use current price (less accurate but works)
        return self.crypto.get_btc_price()

    def _calculate_confidence(self, price_change_pct: float, minutes_left: float) -> float:
        """
        Calculate confidence that current direction will hold.

        Factors:
        - Larger price changes = higher confidence
        - Less time remaining = higher confidence
        """
        # Base confidence from price change (0.1% = 50%, 1% = 90%)
        pct_abs = abs(price_change_pct)
        price_confidence = min(0.5 + (pct_abs * 0.4), 0.95)

        # Time factor (3 min left = 1.0, 0 min left = 1.0, more time = lower)
        time_factor = max(0, 1 - (minutes_left / 15))

        # Combined confidence
        confidence = price_confidence * (0.5 + 0.5 * time_factor)

        return min(confidence, 0.99)

    def _place_bet(self, ticker: str, direction: str, price: int):
        """Place a bet on the market."""
        if direction == "yes":
            order = self.place_order(
                ticker=ticker,
                contracts=self.contracts_per_bet,
                price=price,
                side="buy",
            )
            if order:
                self.log(f"  → BET YES: {self.contracts_per_bet}x @ {price}¢")
        else:
            # Bet NO by selling YES
            order = self.place_order(
                ticker=ticker,
                contracts=self.contracts_per_bet,
                price=price,
                side="sell",
            )
            if order:
                self.log(f"  → BET NO: sold {self.contracts_per_bet}x YES @ {price}¢")


def run_btc_bot(
    kalshi: KalshiClient,
    dry_run: bool = True,
    duration_minutes: int = None,
    check_interval: int = 30,  # Check every 30 seconds
):
    """
    Convenience function to run the BTC bot.

    Args:
        kalshi: Authenticated Kalshi client
        dry_run: If True, don't place real orders
        duration_minutes: How long to run (None = one pass)
        check_interval: Seconds between checks (default 30)
    """
    bot = BTCBotStrategy(
        kalshi=kalshi,
        dry_run=dry_run,
        check_interval=check_interval,
        max_daily_risk=100.0,
    )

    if duration_minutes:
        bot.run(duration_minutes=duration_minutes)
    else:
        # Single pass
        bot.setup()
        bot.on_start()
        bot.on_tick()
        bot.on_stop()
        bot.cleanup()
