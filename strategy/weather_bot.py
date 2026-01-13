"""Weather bot strategy - bucket spread approach with forecast edge."""

from datetime import datetime, timedelta
from typing import Optional

from .base import Strategy
from .spread_selector import select_spread, select_spread_with_edge, calculate_bucket_edges
from clients import KalshiClient, NWSClient
from models import Market, SpreadSelection, Forecast
from config import TradingConfig


class WeatherBotStrategy(Strategy):
    """
    Bucket spread trading strategy for Kalshi weather markets.

    v2: Now uses NWS forecast to find edge (mispricing) before betting.
    Only bets when our forecast probability > market probability.
    """

    def __init__(
        self,
        kalshi: KalshiClient,
        nws: Optional[NWSClient] = None,
        cities: list[str] = None,
        base_contracts: int = 10,
        min_edge: float = 0.05,  # 5% minimum edge
        **kwargs,
    ):
        super().__init__(kalshi=kalshi, **kwargs)

        self.nws = nws or NWSClient()
        self.cities = cities or TradingConfig.CITIES
        self.base_contracts = base_contracts
        self.min_edge = min_edge

        # Track what we've traded today
        self._traded_markets: set[str] = set()

    def setup(self):
        """Initialize strategy."""
        self.log(f"Weather Bot (Forecast Edge) initialized")
        self.log(f"Cities: {self.cities}")
        self.log(f"Min edge: {self.min_edge * 100:.0f}%")
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
        """Process a single city - find spread with edge, place orders."""

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

        # 2. Get NWS forecast (THE KEY CHANGE)
        try:
            forecast = self.nws.get_forecast(city, target_date)
        except Exception as e:
            self.log(f"{city}: Failed to get forecast: {e}")
            return

        if not forecast:
            self.log(f"{city}: No forecast available")
            return

        self.log(f"{city}: NWS forecast high: {forecast.high_temp}°F (±{forecast.high_temp_std}°F)")

        # 3. Calculate edges for all buckets
        edges = calculate_bucket_edges(market, forecast)

        # Show top edges (for debugging/analysis)
        top_edges = [e for e in edges[:5] if e.edge > 0]
        if top_edges:
            self.log(f"{city}: Top edges:")
            for e in top_edges:
                self.log(f"    {e.bucket_range}: {e.edge*100:+.1f}% edge (us: {e.model_prob*100:.0f}%, mkt: {e.market_prob*100:.0f}%)")
        else:
            self.log(f"{city}: No positive edge found (market agrees with forecast)")
            return

        # 4. Select spread with sufficient edge
        spread, _ = select_spread_with_edge(market, forecast, self.min_edge)
        if not spread:
            self.log(f"{city}: No spread with >={self.min_edge*100:.0f}% edge")
            return

        # 5. Log opportunity
        self.log(f"{city}: Found edge spread {spread.range_str}")
        self.log(f"  Buckets: {len(spread.buckets)}, Cost: {spread.total_cost}¢, Potential: +{spread.potential_profit}¢")
        for bucket in spread.buckets:
            edge_info = next((e for e in edges if e.bucket_ticker == bucket.ticker), None)
            edge_str = f", edge: {edge_info.edge*100:+.1f}%" if edge_info else ""
            self.log(f"    {bucket.ticker}: {bucket.yes_bid}¢ bid{edge_str}")

        # 6. Check daily limit
        cost_dollars = (spread.total_cost * self.base_contracts) / 100
        if self._daily_risk + cost_dollars > self.max_daily_risk:
            self.log(f"  Skipping: would exceed daily limit (${self._daily_risk:.2f} + ${cost_dollars:.2f} > ${self.max_daily_risk:.2f})")
            return

        # 7. Place orders
        self._place_spread_orders(spread)

        # 8. Mark as traded
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
