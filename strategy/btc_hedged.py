"""BTC 15-minute hedged strategy - trades every window with loss capping."""

from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass

from .base import Strategy
from clients import KalshiClient
from clients.crypto import BinanceClient
from models import OrderSide


@dataclass
class WindowPosition:
    """Tracks position for a single 15-min window."""
    ticker: str
    entry_side: str  # "long" or "short"
    entry_price: int  # cents
    entry_contracts: int
    entry_btc_price: float
    entry_change_pct: float = 0.0  # BTC % change at entry
    hedged: bool = False
    hedge_price: int = 0
    hedge_contracts: int = 0
    # Settlement tracking
    settled: bool = False
    won: bool = False
    pnl_cents: int = 0  # P&L in cents per contract


class BTCHedgedStrategy(Strategy):
    """
    Hedged BTC 15-minute strategy.
    
    Trades EVERY 15-minute window by:
    1. ENTRY PHASE (10-15 min left): Enter with initial momentum
    2. MONITOR PHASE (3-10 min left): Hedge if direction reverses
    3. HOLD PHASE (0-3 min left): Let it ride
    
    Hedging caps max loss per window to the spread cost.
    """

    def __init__(
        self,
        kalshi: KalshiClient,
        # Position sizing
        base_contracts: int = 10,  # Contracts per entry
        hedge_contracts: int = 10,  # Contracts for hedge (usually same)
        max_price: int = 55,  # Max price to pay (lower = better risk/reward)
        # Timing windows
        entry_window_start: int = 14,  # Enter between 14-10 min before close
        entry_window_end: int = 10,
        hedge_window_start: int = 10,  # Can hedge between 10-3 min before close
        hedge_window_end: int = 3,
        # Thresholds
        min_entry_change: float = 0.05,  # Enter if BTC moved 0.05%+ in any direction
        hedge_trigger_pct: float = 0.25,  # Hedge if reversal exceeds 0.25%
        # Edge requirements
        min_edge_pct: float = 5.0,  # Minimum edge % to enter (entry vs fair value)
        use_limit_orders: bool = True,  # Use mid-price limit orders vs market-taking
        **kwargs,
    ):
        super().__init__(kalshi=kalshi, **kwargs)

        self.base_contracts = base_contracts
        self.hedge_contracts = hedge_contracts
        self.max_price = max_price
        self.entry_window_start = entry_window_start
        self.entry_window_end = entry_window_end
        self.hedge_window_start = hedge_window_start
        self.hedge_window_end = hedge_window_end
        self.min_entry_change = min_entry_change
        self.hedge_trigger_pct = hedge_trigger_pct
        self.min_edge_pct = min_edge_pct
        self.use_limit_orders = use_limit_orders

        self.crypto = BinanceClient(verbose=kwargs.get("verbose", False))

        # Track positions per window
        self._positions: dict[str, WindowPosition] = {}
        self._window_start_prices: dict[str, float] = {}
        self._traded_windows: set[str] = set()

        # Stats
        self._windows_traded = 0
        self._windows_hedged = 0
        self._windows_won = 0
        self._total_pnl_cents = 0

    def setup(self):
        """Initialize strategy."""
        self.log("🔄 BTC Hedged Strategy initialized")
        self.log(f"📦 Base contracts: {self.base_contracts}")
        self.log(f"💰 Max entry price: {self.max_price}¢")
        self.log(f"⏰ Entry window: {self.entry_window_start}-{self.entry_window_end} min before close")
        self.log(f"🛡️ Hedge window: {self.hedge_window_start}-{self.hedge_window_end} min before close")
        self.log(f"📈 Min entry change: {self.min_entry_change}%")
        self.log(f"🔄 Hedge trigger: {self.hedge_trigger_pct}% reversal")
        self.log(f"📊 Min edge: {self.min_edge_pct}%")
        self.log(f"🎯 Limit orders: {self.use_limit_orders}")
        self.log(f"🧪 Dry run: {self.dry_run}")

    def on_start(self):
        """Log starting status."""
        self.log_status()
        btc_price = self.crypto.get_btc_price()
        if btc_price > 0:
            self.log(f"₿ Current BTC: ${btc_price:,.2f}")

    def on_tick(self):
        """Main trading logic."""
        self.log("─" * 60)
        try:
            self._process_window()
        except Exception as e:
            self.log(f"❌ Error: {e}")

    def on_stop(self):
        """Log final stats."""
        self.log("🛑 Hedged Strategy stopping")
        self.log(f"📊 Windows traded: {self._windows_traded}")
        self.log(f"🛡️ Windows hedged: {self._windows_hedged}")
        if self._windows_traded > 0:
            win_rate = (self._windows_won / self._windows_traded) * 100
            self.log(f"✅ Win rate: {self._windows_won}/{self._windows_traded} ({win_rate:.1f}%)")
            self.log(f"💵 Total P&L: ${self._total_pnl_cents / 100:.2f}")
        self.log_status()

    def _process_window(self):
        """Process the current 15-minute window."""
        market = self.kalshi.get_active_btc_market()
        if not market:
            self.log("😴 No active market - waiting for next window...")
            return

        ticker = market.get("ticker", "")
        window_info = self._parse_window(ticker, market)
        if not window_info:
            self.log(f"⚠️ Could not parse window for {ticker}")
            return

        start_time, end_time, minutes_left = window_info

        # Get prices
        start_price = self._get_window_start_price(ticker, start_time)
        current_price = self.crypto.get_btc_price()
        if start_price <= 0 or current_price <= 0:
            self.log("⚠️ Could not get BTC prices")
            return

        price_change_pct = ((current_price - start_price) / start_price) * 100
        is_up = price_change_pct > 0

        # Get market prices
        yes_bid = market.get("yes_bid") or 0
        yes_ask = market.get("yes_ask") or 100

        # Check what phase we're in
        position = self._positions.get(ticker)
        direction = "🟢 UP" if is_up else "🔴 DOWN"

        # Determine phase and log status
        if minutes_left > self.entry_window_start:
            phase = "⏳ PRE-ENTRY"
            self.log(f"{phase} | {ticker} | {minutes_left:.1f}m left | BTC {price_change_pct:+.2f}% {direction}")
            self.log(f"   💹 YES {yes_bid}/{yes_ask}¢ | Waiting for entry window ({self.entry_window_start}m)")

        # ENTRY PHASE: Enter if we haven't yet
        elif self.entry_window_end < minutes_left <= self.entry_window_start:
            phase = "🎯 ENTRY"
            self.log(f"{phase} | {ticker} | {minutes_left:.1f}m left | BTC {price_change_pct:+.2f}% {direction}")
            if ticker not in self._traded_windows:
                self._try_entry(ticker, is_up, price_change_pct, yes_bid, yes_ask, minutes_left)
            else:
                self.log(f"   ✓ Already traded this window")

        # MONITOR PHASE: Check if we need to hedge
        elif self.hedge_window_end < minutes_left <= self.hedge_window_start:
            phase = "🔍 MONITOR"
            pos_status = ""
            if position:
                pos_status = f" | {'LONG' if position.entry_side == 'long' else 'SHORT'} @ {position.entry_price}¢"
                if position.hedged:
                    pos_status += " [HEDGED]"
            self.log(f"{phase} | {ticker} | {minutes_left:.1f}m left | BTC {price_change_pct:+.2f}% {direction}{pos_status}")
            
            if position and not position.hedged:
                self._check_hedge(ticker, position, is_up, price_change_pct, yes_bid, yes_ask, minutes_left)
            elif ticker not in self._traded_windows:
                # Late entry if we missed the window
                self._try_entry(ticker, is_up, price_change_pct, yes_bid, yes_ask, minutes_left)

        # HOLD PHASE: Wait for settlement
        elif minutes_left <= self.hedge_window_end and minutes_left > 0:
            phase = "⏱️ HOLD"
            if position:
                status = "🛡️ HEDGED" if position.hedged else "📈 OPEN"
                self.log(f"{phase} | {ticker} | {minutes_left:.1f}m left | {status} | BTC {price_change_pct:+.2f}% {direction}")
            else:
                self.log(f"{phase} | {ticker} | {minutes_left:.1f}m left | No position | BTC {price_change_pct:+.2f}% {direction}")

        # Window closed
        else:
            # Record settlement if we had a position
            if position and not position.settled:
                self._record_settlement(ticker, is_up)
            self.log(f"🏁 Window closed: {ticker} | Waiting for next...")

    def _calculate_entry_price(self, is_up: bool, yes_bid: int, yes_ask: int) -> int:
        """
        Calculate optimal entry price.
        
        If use_limit_orders is True, use mid-price + small offset.
        Otherwise, hit the ask/bid directly (market-taking).
        """
        if not self.use_limit_orders:
            # Market-taking: hit ask for longs, bid for shorts
            return yes_ask if is_up else yes_bid
        
        # Limit order: use mid-price with small improvement
        mid_price = (yes_bid + yes_ask) // 2
        spread = yes_ask - yes_bid
        
        if is_up:
            # For longs: bid slightly above mid (improves fill chance)
            # But never pay more than ask
            if spread <= 2:
                return yes_ask  # Tight spread, just take it
            return min(mid_price + 1, yes_ask)
        else:
            # For shorts: offer slightly below mid
            # But never go below bid
            if spread <= 2:
                return yes_bid  # Tight spread, just take it
            return max(mid_price - 1, yes_bid)

    def _has_edge(self, is_up: bool, entry_price: int, price_change_pct: float) -> tuple[bool, float, str]:
        """
        Check if entry offers positive expected value.
        
        Returns:
            (has_edge, edge_pct, reason)
        """
        # Fair value estimate based on momentum
        # Stronger momentum = higher probability of continuing
        momentum_strength = abs(price_change_pct)
        
        # Base win probability estimate (rough heuristic)
        # 0.05% move ≈ 55% win rate, 0.10% ≈ 58%, 0.20% ≈ 62%
        estimated_win_pct = 50 + (momentum_strength * 60)  # Cap implicitly by momentum
        estimated_win_pct = min(estimated_win_pct, 70)  # Cap at 70%
        
        if is_up:
            # Buying YES at entry_price, pays 100 if wins
            # EV = win_pct * (100 - entry) - (1 - win_pct) * entry
            fair_value = estimated_win_pct  # Fair price in cents
            edge_pct = ((fair_value - entry_price) / entry_price) * 100
            reason = f"fair={fair_value:.0f}¢ vs entry={entry_price}¢"
        else:
            # Selling YES at entry_price, keeps entry_price if wins (NO wins)
            # EV = (1 - win_pct) * entry - win_pct * (100 - entry)
            fair_value = 100 - estimated_win_pct  # Fair YES price when betting NO
            edge_pct = ((entry_price - fair_value) / fair_value) * 100 if fair_value > 0 else 0
            reason = f"fair={fair_value:.0f}¢ vs entry={entry_price}¢"
        
        has_edge = edge_pct >= self.min_edge_pct
        return has_edge, edge_pct, reason

    def _try_entry(self, ticker: str, is_up: bool, price_change_pct: float, 
                   yes_bid: int, yes_ask: int, minutes_left: float):
        """Attempt to enter a position."""
        direction = "UP" if is_up else "DOWN"
        self.log(f"🎯 {ticker}: Checking entry | BTC {price_change_pct:+.2f}% ({direction}) | {minutes_left:.1f}m left")
        self.log(f"   💹 YES {yes_bid}/{yes_ask}¢")

        # Need minimum movement to have a signal
        if abs(price_change_pct) < self.min_entry_change:
            self.log(f"   ⏳ Waiting for larger move (need {self.min_entry_change}%)")
            return

        # Calculate optimal entry price
        entry_price = self._calculate_entry_price(is_up, yes_bid, yes_ask)
        
        # Check if we have edge at this price
        has_edge, edge_pct, edge_reason = self._has_edge(is_up, entry_price, price_change_pct)
        if not has_edge:
            self.log(f"   ⚠️ No edge: {edge_reason} ({edge_pct:+.1f}% < {self.min_edge_pct}%)")
            return
        
        self.log(f"   📊 Edge: {edge_pct:+.1f}% ({edge_reason})")

        # Determine trade direction and check prices
        if is_up:
            # Want YES to win - BUY YES
            if entry_price > self.max_price:
                self.log(f"   ⛔ Entry {entry_price}¢ > max {self.max_price}¢")
                return
            self._enter_long(ticker, entry_price, self.crypto.get_btc_price(), price_change_pct)
        else:
            # Want NO to win - SELL YES
            no_cost = 100 - entry_price  # What we risk if YES wins
            if no_cost > self.max_price:
                self.log(f"   ⛔ NO risk {no_cost}¢ > max {self.max_price}¢")
                return
            self._enter_short(ticker, entry_price, self.crypto.get_btc_price(), price_change_pct)

    def _enter_long(self, ticker: str, price: int, btc_price: float, change_pct: float):
        """Enter long position (BUY YES)."""
        order = self.place_order(
            ticker=ticker,
            contracts=self.base_contracts,
            price=price,
            side="buy",
        )
        if order:
            self._positions[ticker] = WindowPosition(
                ticker=ticker,
                entry_side="long",
                entry_price=price,
                entry_contracts=self.base_contracts,
                entry_btc_price=btc_price,
                entry_change_pct=change_pct,
            )
            self._traded_windows.add(ticker)
            self._windows_traded += 1
            self.log(f"   ✅ LONG: BUY {self.base_contracts}x YES @ {price}¢")

    def _enter_short(self, ticker: str, price: int, btc_price: float, change_pct: float):
        """Enter short position (SELL YES = bet on NO)."""
        order = self.place_order(
            ticker=ticker,
            contracts=self.base_contracts,
            price=price,
            side="sell",
        )
        if order:
            self._positions[ticker] = WindowPosition(
                ticker=ticker,
                entry_side="short",
                entry_price=price,
                entry_contracts=self.base_contracts,
                entry_btc_price=btc_price,
                entry_change_pct=change_pct,
            )
            self._traded_windows.add(ticker)
            self._windows_traded += 1
            self.log(f"   ✅ SHORT: SELL {self.base_contracts}x YES @ {price}¢")

    def _record_settlement(self, ticker: str, btc_went_up: bool):
        """
        Record the settlement outcome for a position.
        
        Args:
            ticker: Market ticker
            btc_went_up: Whether BTC was up at settlement
        """
        position = self._positions.get(ticker)
        if not position or position.settled:
            return
        
        position.settled = True
        
        # Determine if we won
        if position.entry_side == "long":
            position.won = btc_went_up
            if position.hedged:
                # Hedged: locked in loss at hedge time
                position.pnl_cents = -(position.entry_price - position.hedge_price)
            elif btc_went_up:
                # Won: receive 100¢, paid entry
                position.pnl_cents = 100 - position.entry_price
            else:
                # Lost: paid entry, receive 0
                position.pnl_cents = -position.entry_price
        else:  # short
            position.won = not btc_went_up
            if position.hedged:
                # Hedged: locked in loss
                position.pnl_cents = -(position.hedge_price - position.entry_price)
            elif not btc_went_up:
                # Won (NO won): keep entry price
                position.pnl_cents = position.entry_price
            else:
                # Lost (YES won): lose (100 - entry)
                position.pnl_cents = -(100 - position.entry_price)
        
        # Update totals
        total_pnl = position.pnl_cents * position.entry_contracts
        self._total_pnl_cents += total_pnl
        if position.won:
            self._windows_won += 1
        
        result = "✅ WON" if position.won else "❌ LOST"
        self.log(f"   📋 {ticker}: {result} | P&L: {position.pnl_cents:+d}¢/contract (${total_pnl/100:+.2f} total)")

    def _check_hedge(self, ticker: str, position: WindowPosition, is_up: bool,
                     price_change_pct: float, yes_bid: int, yes_ask: int, minutes_left: float):
        """Check if we should hedge the position."""
        # Calculate if price moved against us
        entry_btc = position.entry_btc_price
        current_btc = self.crypto.get_btc_price()
        move_since_entry = ((current_btc - entry_btc) / entry_btc) * 100

        # Check if direction reversed significantly
        should_hedge = False
        hedge_reason = ""

        if position.entry_side == "long":
            # We're long (betting UP) - hedge if now going DOWN
            if move_since_entry < -self.hedge_trigger_pct:
                should_hedge = True
                hedge_reason = f"reversal {move_since_entry:.2f}%"
        else:
            # We're short (betting DOWN) - hedge if now going UP
            if move_since_entry > self.hedge_trigger_pct:
                should_hedge = True
                hedge_reason = f"reversal +{move_since_entry:.2f}%"

        direction = "UP" if is_up else "DOWN"
        position_side = "LONG" if position.entry_side == "long" else "SHORT"
        self.log(f"🔍 {ticker}: {position_side} @ {position.entry_price}¢ | BTC {price_change_pct:+.2f}% | {minutes_left:.1f}m")

        if should_hedge:
            self._execute_hedge(ticker, position, yes_bid, yes_ask, hedge_reason)

    def _execute_hedge(self, ticker: str, position: WindowPosition, 
                       yes_bid: int, yes_ask: int, reason: str):
        """Execute hedge trade to cap losses."""
        self.log(f"   🛡️ HEDGING: {reason}")

        if position.entry_side == "long":
            # We bought YES - hedge by selling YES (close position)
            # This locks in the loss but prevents further downside
            if yes_bid > 0:
                order = self.place_order(
                    ticker=ticker,
                    contracts=self.hedge_contracts,
                    price=yes_bid,
                    side="sell",
                )
                if order:
                    position.hedged = True
                    position.hedge_price = yes_bid
                    position.hedge_contracts = self.hedge_contracts
                    self._windows_hedged += 1
                    loss = position.entry_price - yes_bid
                    self.log(f"   ✅ HEDGE: SELL {self.hedge_contracts}x @ {yes_bid}¢ (locked ~{loss}¢ loss)")
            else:
                self.log(f"   ⛔ Cannot hedge: no YES bid")
        else:
            # We sold YES - hedge by buying YES (close position)
            if yes_ask <= 99:
                order = self.place_order(
                    ticker=ticker,
                    contracts=self.hedge_contracts,
                    price=yes_ask,
                    side="buy",
                )
                if order:
                    position.hedged = True
                    position.hedge_price = yes_ask
                    position.hedge_contracts = self.hedge_contracts
                    self._windows_hedged += 1
                    loss = yes_ask - position.entry_price
                    self.log(f"   ✅ HEDGE: BUY {self.hedge_contracts}x @ {yes_ask}¢ (locked ~{loss}¢ loss)")
            else:
                self.log(f"   ⛔ Cannot hedge: YES ask too high ({yes_ask}¢)")

    def _parse_window(self, ticker: str, market: dict) -> Optional[tuple[datetime, datetime, float]]:
        """Parse window timing from market data."""
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
        """Get BTC price at window start."""
        if ticker in self._window_start_prices:
            return self._window_start_prices[ticker]

        timestamp_ms = int(start_time.timestamp() * 1000)
        price = self.crypto.get_price_at_time("BTCUSDT", timestamp_ms)

        if price:
            self._window_start_prices[ticker] = price
            return price

        return self.crypto.get_btc_price()


def run_btc_hedged(
    kalshi: KalshiClient,
    dry_run: bool = True,
    duration_minutes: int = None,
    check_interval: int = 15,
    base_contracts: int = 10,
    max_price: int = 70,
):
    """
    Run the hedged BTC strategy.
    
    Args:
        kalshi: Authenticated Kalshi client
        dry_run: If True, don't place real orders
        duration_minutes: How long to run (None = one pass)
        check_interval: Seconds between checks
        base_contracts: Contracts per trade
        max_price: Max price to pay in cents
    """
    bot = BTCHedgedStrategy(
        kalshi=kalshi,
        base_contracts=base_contracts,
        max_price=max_price,
        dry_run=dry_run,
        check_interval=check_interval,
        max_daily_risk=200.0,
    )

    if duration_minutes:
        bot.run(duration_minutes=duration_minutes)
    else:
        bot.setup()
        bot.on_start()
        bot.on_tick()
        bot.on_stop()
        bot.cleanup()
