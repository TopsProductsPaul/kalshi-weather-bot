"""Market and Bucket data models for Kalshi weather markets."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class BucketType(Enum):
    """Type of temperature bucket."""
    TAIL_LOW = "tail_low"    # Below threshold (e.g., <68°F)
    RANGE = "range"          # Temperature range (e.g., 68-69°F)
    TAIL_HIGH = "tail_high"  # Above threshold (e.g., >75°F)


@dataclass
class Bucket:
    """A single temperature bucket within a weather market."""
    ticker: str
    temp_min: Optional[int]  # None for tail_high
    temp_max: Optional[int]  # None for tail_low
    bucket_type: BucketType
    yes_bid: float  # Best bid price (0-100 cents)
    yes_ask: float  # Best ask price (0-100 cents)
    volume: int = 0

    @property
    def midpoint(self) -> float:
        """Midpoint price."""
        return (self.yes_bid + self.yes_ask) / 2

    @property
    def spread(self) -> float:
        """Bid-ask spread in cents."""
        return self.yes_ask - self.yes_bid

    @property
    def implied_prob(self) -> float:
        """Market-implied probability (using ask for buying)."""
        return self.yes_ask / 100

    @property
    def range_str(self) -> str:
        """Human-readable temperature range."""
        if self.bucket_type == BucketType.TAIL_LOW:
            return f"<{self.temp_max}°F"
        elif self.bucket_type == BucketType.TAIL_HIGH:
            return f">{self.temp_min}°F"
        else:
            return f"{self.temp_min}-{self.temp_max}°F"

    def contains_temp(self, temp: float) -> bool:
        """Check if a temperature falls within this bucket."""
        if self.bucket_type == BucketType.TAIL_LOW:
            return temp < self.temp_max
        elif self.bucket_type == BucketType.TAIL_HIGH:
            return temp > self.temp_min
        else:
            return self.temp_min <= temp <= self.temp_max


@dataclass
class Market:
    """A weather market event with multiple buckets."""
    event_ticker: str
    title: str
    city: str
    date: datetime
    buckets: list[Bucket] = field(default_factory=list)
    status: str = "open"
    close_time: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        """Check if market is still open for trading."""
        if self.status != "open":
            return False
        if self.close_time and datetime.now() >= self.close_time:
            return False
        return True

    @property
    def total_implied_prob(self) -> float:
        """Sum of all bucket implied probabilities (should be ~100%)."""
        return sum(b.implied_prob for b in self.buckets)

    def get_bucket(self, ticker: str) -> Optional[Bucket]:
        """Get a specific bucket by ticker."""
        for b in self.buckets:
            if b.ticker == ticker:
                return b
        return None

    def get_buckets_in_range(self, temp_low: float, temp_high: float) -> list[Bucket]:
        """Get all buckets that overlap with a temperature range."""
        result = []
        for b in self.buckets:
            if b.bucket_type == BucketType.TAIL_LOW and b.temp_max > temp_low:
                result.append(b)
            elif b.bucket_type == BucketType.TAIL_HIGH and b.temp_min < temp_high:
                result.append(b)
            elif b.bucket_type == BucketType.RANGE:
                if b.temp_max >= temp_low and b.temp_min <= temp_high:
                    result.append(b)
        return result

    def buckets_by_price(self, ascending: bool = True) -> list[Bucket]:
        """Get buckets sorted by ask price."""
        return sorted(self.buckets, key=lambda b: b.yes_ask, reverse=not ascending)
