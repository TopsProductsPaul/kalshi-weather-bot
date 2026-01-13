"""Spread selection logic for bucket spread strategy."""

from typing import Optional
from models import Market, Bucket, SpreadSelection
from config import TradingConfig


def find_peak_bucket(market: Market) -> Optional[Bucket]:
    """
    Find the peak bucket (highest bid price within acceptable range).

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


def select_spread(market: Market) -> Optional[SpreadSelection]:
    """
    Select the best spread for a market.

    Returns SpreadSelection with 1-2 buckets, or None if no valid spread.
    """
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
