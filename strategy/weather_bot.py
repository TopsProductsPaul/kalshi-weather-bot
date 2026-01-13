"""Weather bot strategy - bucket spread approach."""

from datetime import datetime, timedelta
from typing import Optional

from .base import Strategy
from .spread_selector import select_spread
from clients import KalshiClient
from models import Market, SpreadSelection
from config import TradingConfig


class WeatherBotStrategy(Strategy):
    """
    Bucket spread trading strategy for Kalshi weather markets.

    Buys 2 adjacent temperature buckets (peak + neighbor) to cover
    a wider range with total cost < 95¢.
    """

    def __init__(
        self,
        kalshi: KalshiClient,
        cities: list[str] = None,
        base_contracts: int = 10,
        **kwargs,
    ):
        super().__init__(kalshi=kalshi, **kwargs)

        self.cities = cities or TradingConfig.CITIES
        self.base_contracts = base_contracts

        # Track what we've traded today
        self._traded_markets: set[str] = set()

    def setup(self):
        """Initialize strategy."""
        self.log(f"Weather Bot (Bucket Spread) initialized")
        self.log(f"Cities: {self.cities}")
        self.log(f"Max buckets: {TradingConfig.MAX_BUCKETS}")
        self.log(f"Max total cost: {TradingConfig.MAX_TOTAL_COST}¢")
        self.log(f"Contracts per bucket: {self.base_contracts}")
        self.log(f"Dry run: {self.dry_run}")

    def on_start(self):
        """Log starting status."""
        self.log_status()

    def on_tick(self):
        """Main trading logic - check each city for opportunities."""
        target_date = datetime.now() + timedelta(days=1)  # Tomorrow

        for city in self.cities:
            try:
                self._process_city(city, target_date)
            except Exception as e:
                self.log(f"Error processing {city}: {e}")

    def on_stop(self):
        """Log final status."""
        self.log("Weather Bot stopping")
        self.log_status()
        self.log(f"Markets traded today: {len(self._traded_markets)}")

    def _process_city(self, city: str, target_date: datetime):
        """Process a single city - find spread, place orders."""

        # Skip if already traded this market today
        market_key = f"{city}-{target_date.strftime('%Y%m%d')}"
        if market_key in self._traded_markets:
            return

        # 1. Get weather market
        market = self.kalshi.get_weather_market(city, target_date, "HIGH")
        if not market:
            self.log(f"{city}: No market found for {target_date.date()}")
            return

        if not market.is_open:
            self.log(f"{city}: Market closed")
            return

        # 2. Select spread (peak + neighbor)
        spread = select_spread(market)
        if not spread:
            self.log(f"{city}: No valid spread found")
            return

        # 3. Log opportunity
        self.log(f"{city}: Found spread {spread.range_str}")
        self.log(f"  Buckets: {len(spread.buckets)}, Cost: {spread.total_cost}¢, Potential: +{spread.potential_profit}¢")
        for bucket in spread.buckets:
            self.log(f"    {bucket.ticker}: {bucket.yes_bid}¢ bid")

        # 4. Check daily limit
        cost_dollars = (spread.total_cost * self.base_contracts) / 100
        if self._daily_risk + cost_dollars > self.max_daily_risk:
            self.log(f"  Skipping: would exceed daily limit (${self._daily_risk:.2f} + ${cost_dollars:.2f} > ${self.max_daily_risk:.2f})")
            return

        # 5. Place orders
        self._place_spread_orders(spread)

        # 6. Mark as traded
        self._traded_markets.add(market_key)

    def _place_spread_orders(self, spread: SpreadSelection):
        """Place limit orders for each bucket in the spread."""

        for bucket in spread.buckets:
            # Use bid price for limit orders
            price = bucket.yes_bid
            contracts = self.base_contracts

            order = self.place_order(
                ticker=bucket.ticker,
                contracts=contracts,
                price=price,
                side="buy",
            )

            if order:
                self.log(f"  → Placed order: {contracts}x {bucket.ticker} @ {price}¢")


def run_weather_bot(
    kalshi: KalshiClient,
    cities: list[str] = None,
    dry_run: bool = True,
    duration_minutes: int = None,
):
    """
    Convenience function to run the weather bot.

    Args:
        kalshi: Authenticated Kalshi client
        cities: List of cities to trade (default: NYC only)
        dry_run: If True, don't place real orders
        duration_minutes: How long to run (None = one pass)
    """
    bot = WeatherBotStrategy(
        kalshi=kalshi,
        cities=cities or TradingConfig.CITIES,
        base_contracts=TradingConfig.CONTRACTS_PER_BUCKET,
        dry_run=dry_run,
        check_interval=TradingConfig.CHECK_INTERVAL,
        max_daily_risk=TradingConfig.MAX_DAILY_COST,
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
