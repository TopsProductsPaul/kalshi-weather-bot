"""Unit tests for spread_selector module."""

import pytest
from datetime import datetime
from models import Market, Bucket, BucketType
from strategy.spread_selector import find_peak_bucket, find_best_neighbor, select_spread


def make_bucket(ticker: str, temp_min: int, temp_max: int, yes_bid: float, yes_ask: float) -> Bucket:
    """Helper to create a test bucket."""
    return Bucket(
        ticker=ticker,
        temp_min=temp_min,
        temp_max=temp_max,
        bucket_type=BucketType.RANGE,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
    )


def make_market(buckets: list[Bucket]) -> Market:
    """Helper to create a test market."""
    return Market(
        event_ticker="KXHIGHNY-25JAN13",
        title="NYC High Temperature",
        city="NYC",
        date=datetime(2025, 1, 13),
        buckets=buckets,
    )


class TestFindPeakBucket:
    """Tests for find_peak_bucket()."""

    def test_returns_none_when_no_buckets_in_valid_range(self):
        """Returns None when no buckets are within valid price range (10-60)."""
        buckets = [
            make_bucket("T1", 60, 61, 5, 8),   # bid too low (< 10)
            make_bucket("T2", 62, 63, 70, 75), # bid too high (> 60)
            make_bucket("T3", 64, 65, 3, 5),   # bid too low
        ]
        market = make_market(buckets)

        result = find_peak_bucket(market)

        assert result is None

    def test_returns_bucket_with_highest_bid_in_valid_range(self):
        """Returns the bucket with highest bid within valid price range."""
        buckets = [
            make_bucket("T1", 60, 61, 25, 30),  # valid
            make_bucket("T2", 62, 63, 45, 50),  # valid, highest
            make_bucket("T3", 64, 65, 35, 40),  # valid
            make_bucket("T4", 66, 67, 5, 8),    # invalid (too low)
        ]
        market = make_market(buckets)

        result = find_peak_bucket(market)

        assert result is not None
        assert result.ticker == "T2"
        assert result.yes_bid == 45


class TestFindBestNeighbor:
    """Tests for find_best_neighbor()."""

    def test_returns_none_when_peak_not_in_market(self):
        """Returns None when peak bucket is missing from market buckets."""
        peak = make_bucket("NONEXISTENT", 62, 63, 45, 50)
        buckets = [
            make_bucket("T1", 60, 61, 25, 30),
            make_bucket("T2", 64, 65, 35, 40),
        ]
        market = make_market(buckets)

        result = find_best_neighbor(peak, market)

        assert result is None

    def test_returns_best_adjacent_bucket_based_on_bid(self):
        """Returns best adjacent bucket with highest bid within cost limits."""
        # Buckets sorted by temp: T1(60-61), T2(62-63), T3(64-65)
        buckets = [
            make_bucket("T1", 60, 61, 30, 35),  # left neighbor
            make_bucket("T2", 62, 63, 40, 45),  # peak
            make_bucket("T3", 64, 65, 25, 30),  # right neighbor
        ]
        market = make_market(buckets)
        peak = buckets[1]  # T2 with bid=40

        result = find_best_neighbor(peak, market)

        # T1 has higher bid (30) than T3 (25), both combined costs valid
        # T1 combined: 40 + 30 = 70 < 95, valid
        # T3 combined: 40 + 25 = 65 < 95, valid
        # T1 wins because higher bid
        assert result is not None
        assert result.ticker == "T1"
        assert result.yes_bid == 30


class TestSelectSpread:
    """Tests for select_spread()."""

    def test_returns_none_if_no_peak_bucket_found(self):
        """Returns None if no valid peak bucket exists."""
        buckets = [
            make_bucket("T1", 60, 61, 5, 8),   # below min price
            make_bucket("T2", 62, 63, 70, 75), # above max price
        ]
        market = make_market(buckets)

        result = select_spread(market)

        assert result is None
