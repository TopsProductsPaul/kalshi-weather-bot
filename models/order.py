"""Order data models."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """A trading order."""
    id: str
    ticker: str
    side: OrderSide
    order_type: OrderType
    price: float  # In cents (0-100)
    size: int  # Number of contracts
    filled: int = 0
    status: OrderStatus = OrderStatus.PENDING
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    yes_price: Optional[float] = None  # For YES orders
    no_price: Optional[float] = None   # For NO orders

    @property
    def remaining(self) -> int:
        """Unfilled quantity."""
        return self.size - self.filled

    @property
    def is_active(self) -> bool:
        """Check if order is still active."""
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED, OrderStatus.PENDING)

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.status == OrderStatus.FILLED or self.filled >= self.size

    @property
    def fill_pct(self) -> float:
        """Fill percentage (0-1)."""
        if self.size == 0:
            return 0.0
        return self.filled / self.size

    @property
    def cost(self) -> float:
        """Total cost in dollars."""
        return (self.price * self.size) / 100


@dataclass
class Position:
    """A held position."""
    ticker: str
    contracts: int  # Positive = YES, Negative = NO
    avg_price: float  # Average entry price in cents
    market_price: float = 0.0  # Current market price

    @property
    def side(self) -> str:
        """Position side."""
        return "YES" if self.contracts > 0 else "NO"

    @property
    def cost_basis(self) -> float:
        """Total cost basis in dollars."""
        return (abs(self.contracts) * self.avg_price) / 100

    @property
    def market_value(self) -> float:
        """Current market value in dollars."""
        return (abs(self.contracts) * self.market_price) / 100

    @property
    def unrealized_pnl(self) -> float:
        """Unrealized P&L in dollars."""
        if self.contracts > 0:
            return (self.market_price - self.avg_price) * self.contracts / 100
        else:
            return (self.avg_price - self.market_price) * abs(self.contracts) / 100
