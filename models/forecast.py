"""Weather forecast data models.

NOTE: These models are from the original forecast-based strategy.
Kept for reference but not used by bucket spread strategy.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import math


@dataclass
class Forecast:
    """NWS weather forecast for a location."""
    station: str
    date: datetime
    high_temp: float  # Point forecast high
    low_temp: float   # Point forecast low
    high_temp_std: float = 2.5  # Standard deviation (default ±2.5°F)
    source: str = "NWS"
    fetched_at: Optional[datetime] = None

    @property
    def high_temp_range(self) -> tuple[float, float]:
        """90% confidence interval for high temp."""
        margin = 1.645 * self.high_temp_std  # 90% CI
        return (self.high_temp - margin, self.high_temp + margin)


@dataclass
class ProbabilityDistribution:
    """Probability distribution over temperature buckets."""
    probabilities: dict[str, float] = field(default_factory=dict)
    # Key: bucket range string (e.g., "70-71"), Value: probability (0-1)

    def __post_init__(self):
        """Validate probabilities sum to ~1."""
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 0.01:
            # Normalize if not close to 1
            for k in self.probabilities:
                self.probabilities[k] /= total

    def get(self, bucket_key: str, default: float = 0.0) -> float:
        """Get probability for a bucket."""
        return self.probabilities.get(bucket_key, default)

    def items(self):
        """Iterate over (bucket, probability) pairs."""
        return self.probabilities.items()

    @classmethod
    def from_normal(
        cls,
        mean: float,
        std: float,
        buckets: list[tuple[Optional[int], Optional[int]]]
    ) -> "ProbabilityDistribution":
        """
        Create distribution from normal distribution parameters.

        Args:
            mean: Expected temperature
            std: Standard deviation
            buckets: List of (min_temp, max_temp) tuples.
                     None for tail boundaries.

        Returns:
            ProbabilityDistribution with probability for each bucket
        """
        probs = {}

        for temp_min, temp_max in buckets:
            if temp_min is None:
                # Tail low: P(X < temp_max)
                prob = _normal_cdf(temp_max, mean, std)
                key = f"<{temp_max}"
            elif temp_max is None:
                # Tail high: P(X > temp_min)
                prob = 1 - _normal_cdf(temp_min, mean, std)
                key = f">{temp_min}"
            else:
                # Range: P(temp_min <= X <= temp_max)
                prob = _normal_cdf(temp_max + 0.5, mean, std) - _normal_cdf(temp_min - 0.5, mean, std)
                key = f"{temp_min}-{temp_max}"

            probs[key] = max(0.001, prob)  # Floor at 0.1%

        return cls(probabilities=probs)


@dataclass
class Edge:
    """Calculated edge for a bucket."""
    bucket_ticker: str
    bucket_range: str
    model_prob: float      # Our forecast probability
    market_prob: float     # Market implied probability
    edge: float            # model_prob - market_prob
    expected_value: float  # EV per contract in cents
    market_price: float    # Current ask price in cents

    @property
    def edge_pct(self) -> float:
        """Edge as percentage."""
        return self.edge * 100

    @property
    def has_edge(self) -> bool:
        """Check if edge exceeds typical threshold (5%)."""
        return self.edge > 0.05

    @property
    def kelly_fraction(self) -> float:
        """
        Kelly criterion fraction for optimal bet sizing.
        f* = (bp - q) / b
        where b = odds, p = win prob, q = lose prob
        """
        if self.market_price >= 100 or self.market_price <= 0:
            return 0.0

        # Odds: win $1 for risking market_price cents
        b = (100 - self.market_price) / self.market_price
        p = self.model_prob
        q = 1 - p

        kelly = (b * p - q) / b
        return max(0, kelly)


def _normal_cdf(x: float, mean: float, std: float) -> float:
    """Standard normal CDF approximation."""
    z = (x - mean) / std
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))
