"""Spread selection logic for bucket spread strategy.

v2: Now uses NWS forecast to find edge (mispricing) instead of just
    following market prices.
"""

from typing import Optional
from models import Market, Bucket, SpreadSelection, Forecast, ProbabilityDistribution, Edge
from config import TradingConfig


# Minimum edge required to place a bet (5% = our probability 5% higher than market)
MIN_EDGE = 0.05

# Forecast uncertainty (std dev) by days ahead
FORECAST_STD = {
    0: 2.0,   # Same day: ±2°F
    1: 2.5,   # Tomorrow: ±2.5°F
    2: 3.5,   # 2 days: ±3.5°F
}


def calculate_bucket_edges(
    market: Market,
    forecast: Forecast,
) -> list[Edge]:
    """
    Calculate edge for each bucket by comparing forecast to market.

    Args:
        market: Market with bucket prices
        forecast: NWS forecast with high_temp

    Returns:
        List of Edge objects sorted by edge (highest first)
    """
    # Build probability distribution from forecast
    mean = forecast.high_temp
    std = forecast.high_temp_std

    # Create bucket ranges for probability calculation
    bucket_ranges = []
    for b in market.buckets:
        if b.temp_min is not None and b.temp_max is not None:
            bucket_ranges.append((b.temp_min, b.temp_max))
        elif b.temp_min is None and b.temp_max is not None:
            bucket_ranges.append((None, b.temp_max))
        elif b.temp_max is None and b.temp_min is not None:
            bucket_ranges.append((b.temp_min, None))

    forecast_dist = ProbabilityDistribution.from_normal(mean, std, bucket_ranges)

    # Calculate edge for each bucket
    edges = []
    for bucket in market.buckets:
        # Get our forecast probability for this bucket
        if bucket.temp_min is not None and bucket.temp_max is not None:
            bucket_key = f"{bucket.temp_min}-{bucket.temp_max}"
        elif bucket.temp_min is None:
            bucket_key = f"<{bucket.temp_max}"
        else:
            bucket_key = f">{bucket.temp_min}"

        model_prob = forecast_dist.get(bucket_key, 0.0)

        # Market implied probability (yes_ask price / 100)
        market_prob = bucket.yes_ask / 100 if bucket.yes_ask else bucket.yes_bid / 100

        # Edge = how much higher our probability is vs market
        edge_val = model_prob - market_prob

        # EV = (win_payout * model_prob) - cost
        # Win payout = 100 - price, cost = price
        price = bucket.yes_ask or bucket.yes_bid
        ev = (100 - price) * model_prob - price * (1 - model_prob)

        edges.append(Edge(
            bucket_ticker=bucket.ticker,
            bucket_range=bucket_key,
            model_prob=model_prob,
            market_prob=market_prob,
            edge=edge_val,
            expected_value=ev,
            market_price=price,
        ))

    # Sort by edge (highest first)
    edges.sort(key=lambda e: e.edge, reverse=True)
    return edges


def find_peak_bucket(market: Market) -> Optional[Bucket]:
    """
    Find the peak bucket (highest bid price within acceptable range).
    LEGACY: Used when no forecast available.

    Returns None if no bucket qualifies.
    """
    valid_buckets = [
        b for b in market.buckets
        if TradingConfig.MIN_BUCKET_PRICE <= b.yes_bid <= TradingConfig.MAX_BUCKET_PRICE
    ]

    if not valid_buckets:
        return None

    # Return bucket with highest bid (most likely outcome)
    return max(valid_buckets, key=lambda b: b.yes_bid)


def find_best_neighbor(peak: Bucket, market: Market) -> Optional[Bucket]:
    """
    Find the best neighbor bucket to pair with the peak.
    LEGACY: Used when no forecast available.

    Criteria:
    - Must be adjacent to peak
    - Combined cost < MAX_TOTAL_COST
    - Higher bid price preferred (more likely)
    """
    # Get all buckets sorted by temp
    sorted_buckets = sorted(
        market.buckets,
        key=lambda b: b.temp_min if b.temp_min is not None else -999
    )

    # Find peak index
    try:
        peak_idx = next(i for i, b in enumerate(sorted_buckets) if b.ticker == peak.ticker)
    except StopIteration:
        return None

    candidates = []

    # Check left neighbor
    if peak_idx > 0:
        left = sorted_buckets[peak_idx - 1]
        if left.yes_bid >= TradingConfig.MIN_BUCKET_PRICE:
            combined_cost = peak.yes_bid + left.yes_bid
            if combined_cost < TradingConfig.MAX_TOTAL_COST:
                candidates.append((left, combined_cost))

    # Check right neighbor
    if peak_idx < len(sorted_buckets) - 1:
        right = sorted_buckets[peak_idx + 1]
        if right.yes_bid >= TradingConfig.MIN_BUCKET_PRICE:
            combined_cost = peak.yes_bid + right.yes_bid
            if combined_cost < TradingConfig.MAX_TOTAL_COST:
                candidates.append((right, combined_cost))

    if not candidates:
        return None

    # Prefer higher bid price (more likely to hit)
    return max(candidates, key=lambda x: x[0].yes_bid)[0]


def select_spread_with_edge(
    market: Market,
    forecast: Forecast,
    min_edge: float = MIN_EDGE,
) -> tuple[Optional[SpreadSelection], list[Edge]]:
    """
    Select spread based on forecast edge (NEW METHOD).

    Only selects buckets where our forecast probability exceeds
    market probability by at least min_edge.

    Args:
        market: Market with bucket prices
        forecast: NWS forecast
        min_edge: Minimum edge required (default 5%)

    Returns:
        (SpreadSelection or None, list of all calculated edges)
    """
    edges = calculate_bucket_edges(market, forecast)

    # Filter to buckets with positive edge and acceptable price
    ticker_to_bucket = {b.ticker: b for b in market.buckets}

    selected_buckets = []
    total_cost = 0

    for edge in edges:
        if edge.edge < min_edge:
            continue  # Not enough edge

        bucket = ticker_to_bucket.get(edge.bucket_ticker)
        if not bucket:
            continue

        price = bucket.yes_ask or bucket.yes_bid
        if price > TradingConfig.MAX_BUCKET_PRICE:
            continue  # Too expensive

        if total_cost + price > TradingConfig.MAX_TOTAL_COST:
            continue  # Would exceed cost limit

        if len(selected_buckets) >= TradingConfig.MAX_BUCKETS:
            break  # Max buckets reached

        selected_buckets.append(bucket)
        total_cost += price

    if not selected_buckets:
        return None, edges

    spread = SpreadSelection(buckets=selected_buckets, total_cost=total_cost)

    if not spread.is_valid:
        return None, edges

    return spread, edges


def select_spread(market: Market, forecast: Optional[Forecast] = None) -> Optional[SpreadSelection]:
    """
    Select the best spread for a market.

    If forecast provided: Use edge-based selection (recommended)
    If no forecast: Fall back to legacy market-following method

    Returns SpreadSelection with 1-2 buckets, or None if no valid spread.
    """
    if forecast:
        spread, _ = select_spread_with_edge(market, forecast)
        return spread

    # Legacy fallback (no forecast)
    peak = find_peak_bucket(market)
    if not peak:
        return None

    neighbor = find_best_neighbor(peak, market)

    if neighbor:
        buckets = [peak, neighbor]
        total_cost = peak.yes_bid + neighbor.yes_bid
    else:
        # Single bucket bet is okay
        buckets = [peak]
        total_cost = peak.yes_bid

    spread = SpreadSelection(buckets=buckets, total_cost=total_cost)

    if not spread.is_valid:
        return None

    return spread
