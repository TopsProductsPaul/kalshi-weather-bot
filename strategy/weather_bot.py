"""Weather bot strategy - directional trading based on forecast edge."""

from datetime import datetime, timedelta
from typing import Optional

from .base import Strategy
from clients import KalshiClient, NWSClient
from models import (
    Market, Bucket, BucketType,
    Forecast, ProbabilityDistribution, Edge,
)
from errors import NoEdgeFound, ForecastError


class WeatherBotStrategy(Strategy):
    """
    Directional trading strategy for Kalshi weather markets.

    Edge source: NWS forecasts are more accurate than market-implied probabilities.
    When our forecast probability exceeds market pricing by MIN_EDGE, we buy.
    """

    def __init__(
        self,
        kalshi: KalshiClient,
        nws: NWSClient,
        cities: list[str] = None,
        min_edge: float = 0.05,  # 5% minimum edge to trade
        min_price: int = 10,     # Don't buy below 10¢
        max_price: int = 50,     # Don't buy above 50¢
        base_contracts: int = 10,  # Base position size
        **kwargs,
    ):
        super().__init__(kalshi=kalshi, **kwargs)

        self.nws = nws
        self.cities = cities or ["NYC"]  # Default to NYC only
        self.min_edge = min_edge
        self.min_price = min_price
        self.max_price = max_price
        self.base_contracts = base_contracts

        # Track what we've traded today
        self._traded_markets: set[str] = set()

    def setup(self):
        """Initialize NWS client."""
        self.log(f"Weather Bot initialized")
        self.log(f"Cities: {self.cities}")
        self.log(f"Min edge: {self.min_edge*100:.1f}%")
        self.log(f"Price range: {self.min_price}¢ - {self.max_price}¢")
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
        """Process a single city - get forecast, find edge, place orders."""

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

        # 2. Get forecast
        try:
            forecast = self.nws.get_forecast(city, target_date)
        except Exception as e:
            self.log(f"{city}: Forecast error - {e}")
            return

        # 3. Convert forecast to probability distribution
        prob_dist = self._forecast_to_distribution(forecast, market)

        # 4. Calculate edge for each bucket
        edges = self._calculate_edges(market, prob_dist)

        # 5. Filter for tradeable edges
        tradeable = [e for e in edges if self._is_tradeable(e)]

        if not tradeable:
            self.log(f"{city}: No edge found (forecast: {forecast.high_temp:.0f}°F)")
            return

        # 6. Log opportunities
        self.log(f"{city}: Forecast {forecast.high_temp:.0f}°F ±{forecast.high_temp_std:.1f}°F")
        for edge in tradeable:
            self.log(f"  {edge.bucket_range}: model={edge.model_prob*100:.1f}% vs market={edge.market_prob*100:.1f}% → edge={edge.edge_pct:.1f}%")

        # 7. Place orders on best opportunities
        self._place_orders(tradeable)

        # Mark as traded
        self._traded_markets.add(market_key)

    def _forecast_to_distribution(
        self,
        forecast: Forecast,
        market: Market
    ) -> ProbabilityDistribution:
        """Convert NWS forecast to probability distribution over market buckets."""

        # Extract bucket ranges from market
        bucket_ranges = []
        for bucket in market.buckets:
            bucket_ranges.append((bucket.temp_min, bucket.temp_max))

        # Get uncertainty estimate
        days_ahead = (forecast.date.date() - datetime.now().date()).days
        uncertainty = self.nws.estimate_forecast_uncertainty(market.city, days_ahead)

        # Create normal distribution centered on forecast
        return ProbabilityDistribution.from_normal(
            mean=forecast.high_temp,
            std=uncertainty,
            buckets=bucket_ranges,
        )

    def _calculate_edges(
        self,
        market: Market,
        prob_dist: ProbabilityDistribution
    ) -> list[Edge]:
        """Calculate edge for each bucket."""
        edges = []

        for bucket in market.buckets:
            # Get our probability
            model_prob = prob_dist.get(bucket.range_str, 0.0)

            # Get market probability (using ask price for buying)
            market_prob = bucket.implied_prob

            # Calculate edge
            edge = model_prob - market_prob

            # Calculate expected value per contract (in cents)
            # EV = P(win) * $1 - P(lose) * cost
            # EV = model_prob * (100 - price) - (1 - model_prob) * price
            ev = model_prob * (100 - bucket.yes_ask) - (1 - model_prob) * bucket.yes_ask

            edges.append(Edge(
                bucket_ticker=bucket.ticker,
                bucket_range=bucket.range_str,
                model_prob=model_prob,
                market_prob=market_prob,
                edge=edge,
                expected_value=ev,
                market_price=bucket.yes_ask,
            ))

        return edges

    def _is_tradeable(self, edge: Edge) -> bool:
        """Check if an edge is worth trading."""
        # Must have positive edge above threshold
        if edge.edge < self.min_edge:
            return False

        # Price must be in acceptable range
        if edge.market_price < self.min_price or edge.market_price > self.max_price:
            return False

        # EV must be positive
        if edge.expected_value <= 0:
            return False

        return True

    def _place_orders(self, edges: list[Edge]):
        """Place orders on tradeable edges."""

        # Sort by edge (highest first)
        edges = sorted(edges, key=lambda e: e.edge, reverse=True)

        for edge in edges[:3]:  # Max 3 positions per market
            # Size based on edge magnitude (simple linear scaling)
            size_multiplier = min(2.0, edge.edge / self.min_edge)
            contracts = int(self.base_contracts * size_multiplier)

            # Kelly fraction for more sophisticated sizing (optional)
            # kelly = edge.kelly_fraction
            # contracts = int(self.base_contracts * kelly * 0.5)  # Half-Kelly

            price = int(edge.market_price)

            order = self.place_order(
                ticker=edge.bucket_ticker,
                contracts=contracts,
                price=price,
                side="buy",
            )

            if order:
                self.log(f"  → Bought {contracts}x {edge.bucket_range} @ {price}¢ (edge={edge.edge_pct:.1f}%)")


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
    nws = NWSClient()

    bot = WeatherBotStrategy(
        kalshi=kalshi,
        nws=nws,
        cities=cities or ["NYC"],
        dry_run=dry_run,
        check_interval=300,  # 5 minutes
        max_daily_risk=50.0,  # $50 max risk per day
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
