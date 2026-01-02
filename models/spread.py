"""Spread selection models."""

from dataclasses import dataclass
from typing import Optional
from .market import Bucket


@dataclass
class SpreadSelection:
    """A selected spread of buckets to buy."""

    buckets: list[Bucket]
    total_cost: int  # In cents (sum of bid prices)

    @property
    def is_valid(self) -> bool:
        """Check if spread is under cost limit."""
        return self.total_cost < 95 and len(self.buckets) > 0

    @property
    def potential_profit(self) -> int:
        """Profit in cents if we win (100 - cost)."""
        return 100 - self.total_cost

    @property
    def tickers(self) -> list[str]:
        """List of bucket tickers in the spread."""
        return [b.ticker for b in self.buckets]

    @property
    def range_str(self) -> str:
        """Human-readable range string."""
        if not self.buckets:
            return ""
        temps = []
        for b in self.buckets:
            if b.temp_min is not None and b.temp_max is not None:
                temps.extend([b.temp_min, b.temp_max])
            elif b.temp_min is not None:
                temps.append(b.temp_min)
            elif b.temp_max is not None:
                temps.append(b.temp_max)
        if temps:
            return f"{min(temps)}-{max(temps)}°F"
        return ""
