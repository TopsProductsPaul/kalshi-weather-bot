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
        min_confidence: float = 0.65,  # Minimum confidence to bet (0-1) - raised for momentum
        max_minutes_before_close: int = 10,  # Start betting at 10 min left
        min_minutes_before_close: int = 2,  # Stop betting at 2 min left
        min_price_change_pct: float = 0.05,  # Min % change (5 bps) - lowered for earlier signals
        contracts_per_bet: int = 10,  # Max contracts at high confidence
        min_contracts: int = 2,  # Min contracts at low confidence
        max_price: int = 95,  # Don't pay more than 95¢
        scale_by_confidence: bool = True,  # Scale position size by confidence
        **kwargs,
    ):
        super().__init__(kalshi=kalshi, **kwargs)

        self.min_confidence = min_confidence
        self.max_minutes_before_close = max_minutes_before_close
        self.min_minutes_before_close = min_minutes_before_close
        self.min_price_change_pct = min_price_change_pct
        self.contracts_per_bet = contracts_per_bet
        self.min_contracts = min_contracts
        self.max_price = max_price
        self.scale_by_confidence = scale_by_confidence

        # Crypto price client
        self.crypto = BinanceClient(verbose=kwargs.get("verbose", False))

        # Track what we've traded
        self._traded_markets: set[str] = set()
        self._window_start_prices: dict[str, float] = {}
        self._price_history: list[float] = []  # Track last 3-4 price updates for momentum

    def setup(self):
        """Initialize strategy."""
        self.log("BTC 15M Bot initialized")
        self.log(f"Min confidence: {self.min_confidence:.0%}")
        self.log(f"Bet window: {self.max_minutes_before_close}-{self.min_minutes_before_close} minutes before close")
        self.log(f"Min price change: {self.min_price_change_pct}%")
        self.log(f"Max price: {self.max_price}¢")
        if self.scale_by_confidence:
            self.log(f"Contracts: {self.min_contracts}-{self.contracts_per_bet} (scaled by confidence)")
        else:
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

        # Only trade in the betting window (between max and min minutes before close)
        if minutes_left > self.max_minutes_before_close:
            self.log(f"{ticker}: {minutes_left:.1f} min left (waiting for {self.max_minutes_before_close} min window)")
            return
        if minutes_left < self.min_minutes_before_close:
            self.log(f"{ticker}: {minutes_left:.1f} min left (past {self.min_minutes_before_close} min cutoff)")
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

        # Track price for momentum detection
        self._price_history.append(current_price)
        if len(self._price_history) > 4:
            self._price_history = self._price_history[-4:]

        # Check for momentum
        has_momentum = self._detect_momentum(is_up)

        self.log(f"{ticker}: BTC ${start_price:,.0f} → ${current_price:,.0f} ({price_change_pct:+.2f}%)")
        self.log(f"  Minutes left: {minutes_left:.1f}, Direction: {'UP' if is_up else 'DOWN'}, Momentum: {has_momentum}")

        # Check if outcome is nearly certain
        if abs(price_change_pct) < self.min_price_change_pct:
            self.log(f"  Price change too small ({abs(price_change_pct):.2f}% < {self.min_price_change_pct}%)")
            return

        # Get market prices
        yes_bid = market.get("yes_bid") or 0
        yes_ask = market.get("yes_ask") or 100
        no_bid = 100 - yes_ask  # NO bid = 100 - YES ask
        no_ask = 100 - yes_bid if yes_bid > 0 else 100  # NO ask = 100 - YES bid

        self.log(f"  Market: YES {yes_bid}/{yes_ask}¢ | NO {no_bid}/{no_ask}¢")

        # Calculate our confidence based on price movement, time left, and momentum
        confidence = self._calculate_confidence(price_change_pct, minutes_left, has_momentum)
        self.log(f"  Confidence: {confidence:.0%}")

        if confidence < self.min_confidence:
            self.log(f"  Confidence too low ({confidence:.0%} < {self.min_confidence:.0%})")
            return

        # Calculate position size based on confidence
        contracts = self._scale_contracts(confidence)
        self.log(f"  Position size: {contracts} contracts")

        # Find the best trade option among all 4 possibilities
        # "BTC up in next 15 mins" = YES means price went up
        trade_executed = False

        if is_up:
            # Price is UP - we want exposure to YES winning
            # Option 1: BUY YES at ask price
            # Option 2: SELL NO at bid price (equivalent exposure)
            trade_executed = self._execute_best_up_trade(ticker, yes_ask, no_bid, contracts, confidence)
        else:
            # Price is DOWN - we want exposure to NO winning
            # Option 1: BUY NO at ask price (= SELL YES at bid)
            # Option 2: SELL YES at bid price
            trade_executed = self._execute_best_down_trade(ticker, yes_bid, no_ask, contracts, confidence)

        if trade_executed:
            self._traded_markets.add(ticker)

    def _execute_best_up_trade(self, ticker: str, yes_ask: int, no_bid: int, contracts: int, confidence: float) -> bool:
        """
        Execute the best trade when price is UP (we want YES to win).
        
        Options:
        1. BUY YES at yes_ask - costs yes_ask per contract, profits (100 - yes_ask)
        2. SELL NO at no_bid - receives no_bid per contract, profits no_bid if YES wins
        
        Returns True if trade was executed.
        """
        # Calculate effective costs and profits
        buy_yes_cost = yes_ask
        buy_yes_profit = 100 - yes_ask  # What we make if YES wins
        
        sell_no_profit = no_bid  # What we keep if YES wins (NO expires worthless)
        sell_no_risk = 100 - no_bid  # What we lose if NO wins
        
        self.log(f"  UP Trade Options:")
        self.log(f"    BUY YES @ {yes_ask}¢ → profit {buy_yes_profit}¢ if YES wins")
        self.log(f"    SELL NO @ {no_bid}¢ → profit {no_bid}¢ if YES wins (risk {sell_no_risk}¢)")
        
        # Prefer BUY YES if price is reasonable
        if buy_yes_cost <= self.max_price:
            self._place_bet(ticker, "buy_yes", yes_ask, contracts, confidence)
            return True
        
        # If BUY YES too expensive, try SELL NO if profitable
        # SELL NO makes sense when no_bid > 0 (we receive premium)
        # This is equivalent to betting YES will win when YES price is very high
        if no_bid > 0 and sell_no_risk <= self.max_price:
            self.log(f"  → YES ask too high ({yes_ask}¢), using SELL NO instead")
            self._place_bet(ticker, "sell_no", no_bid, contracts, confidence)
            return True
        
        self.log(f"  No viable UP trade: YES ask {yes_ask}¢ > max {self.max_price}¢, NO bid {no_bid}¢")
        return False

    def _execute_best_down_trade(self, ticker: str, yes_bid: int, no_ask: int, contracts: int, confidence: float) -> bool:
        """
        Execute the best trade when price is DOWN (we want NO to win).
        
        Options:
        1. BUY NO at no_ask (= 100 - yes_bid) - costs no_ask, profits (100 - no_ask)
        2. SELL YES at yes_bid - receives yes_bid, profits yes_bid if NO wins
        
        Returns True if trade was executed.
        """
        # Calculate effective costs and profits
        buy_no_cost = no_ask
        buy_no_profit = 100 - no_ask  # What we make if NO wins
        
        sell_yes_profit = yes_bid  # What we keep if NO wins (YES expires worthless)
        sell_yes_risk = 100 - yes_bid  # What we lose if YES wins
        
        self.log(f"  DOWN Trade Options:")
        self.log(f"    BUY NO @ {no_ask}¢ → profit {buy_no_profit}¢ if NO wins")
        self.log(f"    SELL YES @ {yes_bid}¢ → profit {yes_bid}¢ if NO wins (risk {sell_yes_risk}¢)")
        
        # Prefer direct BUY NO (via SELL YES) if price is reasonable
        if buy_no_cost <= self.max_price and yes_bid > 0:
            self._place_bet(ticker, "sell_yes", yes_bid, contracts, confidence)
            return True
        
        # If BUY NO too expensive, try SELL YES if profitable
        # SELL YES makes sense when yes_bid > 0 (we receive premium)
        # This captures opportunities where NO is very expensive but YES bid is available
        if yes_bid > 0 and sell_yes_risk <= self.max_price:
            self.log(f"  → NO ask too high ({no_ask}¢), using SELL YES instead")
            self._place_bet(ticker, "sell_yes", yes_bid, contracts, confidence)
            return True
        
        # Last resort: if yes_bid is very low (< 5¢), we can sell YES cheaply
        # Risk is high but probability of loss is low given our confidence
        if yes_bid > 0 and yes_bid <= 5 and confidence >= 0.75:
            self.log(f"  → High confidence ({confidence:.0%}), SELL YES @ {yes_bid}¢ despite high risk")
            self._place_bet(ticker, "sell_yes", yes_bid, contracts, confidence)
            return True
        
        self.log(f"  No viable DOWN trade: NO ask {no_ask}¢ > max {self.max_price}¢, YES bid {yes_bid}¢")
        return False

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

    def _detect_momentum(self, is_up: bool) -> bool:
        """
        Detect if price has momentum in the expected direction.

        Checks if at least 2 consecutive moves are in the same direction
        and that direction aligns with current price movement.

        Returns:
            True if momentum confirms the direction, False otherwise
        """
        if len(self._price_history) < 3:
            return False

        # Check last 3 price changes
        changes = []
        for i in range(1, len(self._price_history)):
            changes.append(self._price_history[i] - self._price_history[i - 1])

        # Count consecutive moves in same direction
        consecutive_up = sum(1 for c in changes if c > 0)
        consecutive_down = sum(1 for c in changes if c < 0)

        # Momentum confirmed if at least 2 moves align with current direction
        if is_up and consecutive_up >= 2:
            return True
        if not is_up and consecutive_down >= 2:
            return True

        return False

    def _calculate_confidence(self, price_change_pct: float, minutes_left: float, has_momentum: bool = False) -> float:
        """
        Calculate confidence that current direction will hold.

        Factors:
        - Larger price changes = higher confidence
        - Less time remaining = higher confidence
        - Momentum confirmation = +15% boost
        - Large move (0.15%+) = +10% boost
        """
        # Base confidence from price change (0.05% = 50%, 1% = 90%)
        pct_abs = abs(price_change_pct)
        price_confidence = min(0.5 + (pct_abs * 0.4), 0.95)

        # Time factor (10 min left = lower, 2 min left = higher)
        time_factor = max(0, 1 - (minutes_left / 15))

        # Combined confidence
        confidence = price_confidence * (0.5 + 0.5 * time_factor)

        # Momentum boost: +15% if momentum is detected
        if has_momentum:
            confidence += 0.15

        # Large move boost: +10% if move is 0.15%+ (late-stage certainty)
        if pct_abs >= 0.15:
            confidence += 0.10

        return min(confidence, 0.99)

    def _scale_contracts(self, confidence: float) -> int:
        """
        Scale position size based on confidence level.
        
        50% confidence → min_contracts (2)
        100% confidence → contracts_per_bet (10)
        Linear interpolation between.
        """
        if not self.scale_by_confidence:
            return self.contracts_per_bet
        
        # Linear scale: min_confidence → min_contracts, 1.0 → max_contracts
        conf_range = 1.0 - self.min_confidence
        conf_pct = (confidence - self.min_confidence) / conf_range if conf_range > 0 else 1.0
        
        contracts = self.min_contracts + conf_pct * (self.contracts_per_bet - self.min_contracts)
        return max(self.min_contracts, min(int(contracts), self.contracts_per_bet))

    def _place_bet(self, ticker: str, trade_type: str, price: int, contracts: int, confidence: float = 0.0):
        """
        Place a bet on the market.
        
        Args:
            ticker: Market ticker
            trade_type: One of "buy_yes", "sell_yes", "buy_no", "sell_no"
            price: Price in cents
            contracts: Number of contracts
            confidence: Confidence level for logging
        """
        order = None
        
        if trade_type == "buy_yes":
            # BUY YES - pay yes_ask, win 100¢ if YES wins
            order = self.place_order(
                ticker=ticker,
                contracts=contracts,
                price=price,
                side="buy",
            )
            if order:
                self.log(f"  → BUY YES: {contracts}x @ {price}¢ ({confidence:.0%} conf)")
                
        elif trade_type == "sell_yes":
            # SELL YES - receive yes_bid, keep it if NO wins
            order = self.place_order(
                ticker=ticker,
                contracts=contracts,
                price=price,
                side="sell",
            )
            if order:
                self.log(f"  → SELL YES: {contracts}x @ {price}¢ ({confidence:.0%} conf)")
                
        elif trade_type == "buy_no":
            # BUY NO - on Kalshi this is done by selling YES
            # When we sell YES at yes_bid, we're effectively buying NO at (100 - yes_bid)
            # But we want to specify we're buying NO at no_ask price
            # no_ask = 100 - yes_bid, so yes_bid = 100 - no_ask = 100 - price
            yes_price = 100 - price
            order = self.place_order(
                ticker=ticker,
                contracts=contracts,
                price=yes_price,
                side="sell",
            )
            if order:
                self.log(f"  → BUY NO: {contracts}x @ {price}¢ (via SELL YES @ {yes_price}¢) ({confidence:.0%} conf)")
                
        elif trade_type == "sell_no":
            # SELL NO - on Kalshi this is done by buying YES
            # When we buy YES at yes_ask, we're effectively selling NO at (100 - yes_ask)
            # no_bid = 100 - yes_ask, so yes_ask = 100 - no_bid = 100 - price
            yes_price = 100 - price
            order = self.place_order(
                ticker=ticker,
                contracts=contracts,
                price=yes_price,
                side="buy",
            )
            if order:
                self.log(f"  → SELL NO: {contracts}x @ {price}¢ (via BUY YES @ {yes_price}¢) ({confidence:.0%} conf)")
        
        return order


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
