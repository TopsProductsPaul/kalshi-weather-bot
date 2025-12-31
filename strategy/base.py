"""Base strategy class with lifecycle hooks."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
import time

from clients import KalshiClient
from models import Market, Order, Position


class Strategy(ABC):
    """
    Base class for trading strategies.

    Provides lifecycle hooks and common utilities.
    Subclasses must implement on_tick() with trading logic.
    """

    def __init__(
        self,
        kalshi: KalshiClient,
        check_interval: int = 60,  # seconds between ticks
        max_daily_risk: float = 100.0,  # max $ at risk per day
        dry_run: bool = True,  # if True, don't place real orders
    ):
        self.kalshi = kalshi
        self.check_interval = check_interval
        self.max_daily_risk = max_daily_risk
        self.dry_run = dry_run

        # State
        self._running = False
        self._daily_risk = 0.0
        self._orders_placed: list[Order] = []
        self._start_time: Optional[datetime] = None

    # Lifecycle hooks

    def setup(self):
        """Called once before run loop starts. Override to initialize."""
        pass

    def on_start(self):
        """Called at the beginning of run(). Override for custom logic."""
        pass

    @abstractmethod
    def on_tick(self):
        """
        Main trading logic. Called every check_interval seconds.
        Must be implemented by subclasses.
        """
        pass

    def on_stop(self):
        """Called when run() ends. Override for cleanup."""
        pass

    def cleanup(self):
        """Called after on_stop(). Cancel orders, close connections."""
        self.kalshi.close()

    # Main run loop

    def run(self, duration_minutes: Optional[int] = None):
        """
        Main execution loop.

        Args:
            duration_minutes: How long to run (None = indefinitely)
        """
        self._running = True
        self._start_time = datetime.now()

        try:
            self.setup()
            self.on_start()

            end_time = None
            if duration_minutes:
                end_time = datetime.now().timestamp() + (duration_minutes * 60)

            while self._running:
                try:
                    self.on_tick()
                except Exception as e:
                    self.log(f"Error in on_tick: {e}")

                # Check if we should stop
                if end_time and time.time() >= end_time:
                    self.log("Duration reached, stopping")
                    break

                # Sleep until next tick
                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            self.log("Interrupted by user")
        finally:
            self._running = False
            self.on_stop()
            self.cleanup()

    def stop(self):
        """Signal the run loop to stop."""
        self._running = False

    # Trading utilities

    def place_order(
        self,
        ticker: str,
        contracts: int,
        price: int,
        side: str = "buy",
    ) -> Optional[Order]:
        """
        Place an order with risk checks.

        Args:
            ticker: Market ticker
            contracts: Number of contracts
            price: Price in cents
            side: "buy" or "sell"

        Returns:
            Order object if placed, None if blocked by risk limits
        """
        from models import OrderSide, OrderType

        # Risk check
        cost = (contracts * price) / 100
        if self._daily_risk + cost > self.max_daily_risk:
            self.log(f"Risk limit: would exceed daily max (${self._daily_risk:.2f} + ${cost:.2f} > ${self.max_daily_risk:.2f})")
            return None

        if self.dry_run:
            self.log(f"[DRY RUN] Would place: {side.upper()} {contracts}x {ticker} @ {price}¢")
            return None

        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        order = self.kalshi.place_order(
            ticker=ticker,
            side=order_side,
            contracts=contracts,
            price=price,
            order_type=OrderType.LIMIT,
        )

        self._daily_risk += cost
        self._orders_placed.append(order)
        self.log(f"Placed: {side.upper()} {contracts}x {ticker} @ {price}¢ (order {order.id})")

        return order

    def get_balance(self) -> float:
        """Get current account balance."""
        return self.kalshi.get_balance()

    def get_positions(self) -> list[Position]:
        """Get current positions."""
        return self.kalshi.get_positions()

    def get_open_orders(self) -> list[Order]:
        """Get open orders."""
        return self.kalshi.get_open_orders()

    # Logging

    def log(self, message: str):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    def log_status(self):
        """Log current status."""
        balance = self.get_balance()
        positions = self.get_positions()
        orders = self.get_open_orders()

        self.log(f"Balance: ${balance:.2f}")
        self.log(f"Positions: {len(positions)}")
        self.log(f"Open orders: {len(orders)}")
        self.log(f"Daily risk used: ${self._daily_risk:.2f} / ${self.max_daily_risk:.2f}")
