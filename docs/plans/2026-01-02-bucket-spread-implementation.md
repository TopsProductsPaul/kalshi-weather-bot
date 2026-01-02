# Bucket Spread Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace forecast-based edge strategy with bucket spread approach that buys 2 adjacent temperature buckets.

**Architecture:** Find peak bucket (highest bid), select best neighbor, place limit orders at bid price. Total cost must be < 95¢.

**Tech Stack:** Python 3.13, httpx, existing Kalshi client (already supports limit orders)

---

## Task 1: Update Config with Spread Parameters

**Files:**
- Modify: `config.py:21-36`

**Step 1: Replace TradingConfig class**

Replace the entire `TradingConfig` class with:

```python
class TradingConfig:
    # Bucket spread strategy
    MIN_BUCKET_PRICE = 10         # Don't buy below 10¢ (too unlikely)
    MAX_BUCKET_PRICE = 60         # Allow up to 60¢ (peaks are 35-57¢)
    MAX_BUCKETS = 2               # Prevents >100¢ cost
    MAX_TOTAL_COST = 95           # Safety cap in cents
    CONTRACTS_PER_BUCKET = 10     # Fixed size per bucket
    USE_LIMIT_ORDERS = True       # Buy at bid, not ask
    MAX_DAILY_COST = 100          # Total $ to deploy per day

    # Cities (LA and Chicago have better spreads)
    CITIES = ["NYC", "LA", "CHICAGO", "MIAMI"]

    # Timing
    CHECK_INTERVAL = 300          # seconds between checks (5 min)
```

**Step 2: Verify config loads**

Run: `source venv/bin/activate && python -c "from config import TradingConfig; print(TradingConfig.MAX_BUCKETS)"`

Expected: `2`

**Step 3: Commit**

```bash
git add config.py
git commit -m "Update config for bucket spread strategy"
```

---

## Task 2: Add Spread Selection Model

**Files:**
- Create: `models/spread.py`
- Modify: `models/__init__.py`

**Step 1: Create spread.py**

Create new file `models/spread.py`:

```python
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
```

**Step 2: Update models/__init__.py**

Add to imports:

```python
from .spread import SpreadSelection
```

Add to `__all__`:

```python
"SpreadSelection",
```

**Step 3: Verify import works**

Run: `source venv/bin/activate && python -c "from models import SpreadSelection; print('OK')"`

Expected: `OK`

**Step 4: Commit**

```bash
git add models/spread.py models/__init__.py
git commit -m "Add SpreadSelection model"
```

---

## Task 3: Create Spread Selector Logic

**Files:**
- Create: `strategy/spread_selector.py`

**Step 1: Create spread_selector.py**

```python
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
```

**Step 2: Verify import works**

Run: `source venv/bin/activate && python -c "from strategy.spread_selector import select_spread; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
git add strategy/spread_selector.py
git commit -m "Add spread selector logic"
```

---

## Task 4: Update Strategy __init__.py

**Files:**
- Modify: `strategy/__init__.py`

**Step 1: Check current exports**

Read `strategy/__init__.py` first.

**Step 2: Add spread_selector export**

Add to the file:

```python
from .spread_selector import select_spread, find_peak_bucket, find_best_neighbor
```

**Step 3: Commit**

```bash
git add strategy/__init__.py
git commit -m "Export spread selector from strategy module"
```

---

## Task 5: Rewrite WeatherBotStrategy.on_tick()

**Files:**
- Modify: `strategy/weather_bot.py`

**Step 1: Add imports at top**

Add after existing imports:

```python
from .spread_selector import select_spread
from models import SpreadSelection
```

**Step 2: Replace _process_city method**

Replace the entire `_process_city` method (around line 74-121) with:

```python
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
    if self._daily_spent + cost_dollars > self.max_daily_risk:
        self.log(f"  Skipping: would exceed daily limit (${self._daily_spent:.2f} + ${cost_dollars:.2f} > ${self.max_daily_risk:.2f})")
        return

    # 5. Place orders
    self._place_spread_orders(spread)

    # 6. Mark as traded
    self._traded_markets.add(market_key)
```

**Step 3: Replace _place_orders with _place_spread_orders**

Replace the `_place_orders` method (around line 197-222) with:

```python
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
```

**Step 4: Remove old methods**

Delete these methods (no longer needed):
- `_forecast_to_distribution`
- `_calculate_edges`
- `_is_tradeable`

**Step 5: Remove NWS dependency from __init__**

In `__init__`, remove the `nws` parameter and `self.nws` assignment. Also remove unused params like `min_edge`, `min_price`, `max_price`.

New `__init__` signature:

```python
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
```

**Step 6: Update setup() method**

```python
def setup(self):
    """Initialize strategy."""
    self.log(f"Weather Bot (Bucket Spread) initialized")
    self.log(f"Cities: {self.cities}")
    self.log(f"Max buckets: {TradingConfig.MAX_BUCKETS}")
    self.log(f"Max total cost: {TradingConfig.MAX_TOTAL_COST}¢")
    self.log(f"Contracts per bucket: {self.base_contracts}")
    self.log(f"Dry run: {self.dry_run}")
```

**Step 7: Verify syntax**

Run: `source venv/bin/activate && python -c "from strategy import WeatherBotStrategy; print('OK')"`

Expected: `OK`

**Step 8: Commit**

```bash
git add strategy/weather_bot.py
git commit -m "Rewrite strategy with bucket spread logic"
```

---

## Task 6: Update main.py

**Files:**
- Modify: `main.py`

**Step 1: Remove NWS initialization**

Remove the line:
```python
nws = NWSClient(verbose=args.verbose)
```

**Step 2: Update bot initialization**

Replace the bot creation (around line 81-92) with:

```python
# Create and run strategy
bot = WeatherBotStrategy(
    kalshi=kalshi,
    cities=cities,
    base_contracts=TradingConfig.BASE_POSITION_SIZE if hasattr(TradingConfig, 'BASE_POSITION_SIZE') else TradingConfig.CONTRACTS_PER_BUCKET,
    dry_run=dry_run,
    check_interval=TradingConfig.CHECK_INTERVAL,
    max_daily_risk=TradingConfig.MAX_DAILY_COST,
)
```

**Step 3: Update print statements**

Replace the config print block (around line 74-78) with:

```python
print(f"\nMode: {'LIVE TRADING' if args.live else 'DRY RUN'}")
print(f"Cities: {cities}")
print(f"Max buckets: {TradingConfig.MAX_BUCKETS}")
print(f"Max cost per spread: {TradingConfig.MAX_TOTAL_COST}¢")
print(f"Max daily spend: ${TradingConfig.MAX_DAILY_COST:.0f}")
print()
```

**Step 4: Remove unused import**

Remove from imports:
```python
from clients import KalshiClient, NWSClient
```

Replace with:
```python
from clients import KalshiClient
```

**Step 5: Verify script runs**

Run: `source venv/bin/activate && python main.py --help`

Expected: Help text without errors

**Step 6: Commit**

```bash
git add main.py
git commit -m "Update main.py for bucket spread strategy"
```

---

## Task 7: Test Dry Run

**Files:** None (testing only)

**Step 1: Run dry run**

Run: `source venv/bin/activate && python main.py --verbose`

Expected output should show:
- Connecting to Kalshi
- Finding spreads for each city
- Logging bucket selections
- NOT placing real orders (dry run)

**Step 2: Check for errors**

If errors, fix them before proceeding.

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "Fix issues found during dry run testing"
```

---

## Task 8: Final Cleanup

**Files:**
- Modify: `models/forecast.py` (optional: remove unused code)
- Modify: `clients/nws.py` (optional: keep for reference)

**Step 1: Add note to forecast.py**

Add comment at top of `models/forecast.py`:

```python
# NOTE: These models are from the original forecast-based strategy.
# Kept for reference but not used by bucket spread strategy.
```

**Step 2: Final commit**

```bash
git add -A
git commit -m "Complete bucket spread strategy implementation"
```

---

## Summary

After completing all tasks:

1. ✅ Config updated with spread parameters
2. ✅ SpreadSelection model created
3. ✅ Spread selector logic implemented
4. ✅ WeatherBotStrategy rewritten
5. ✅ main.py updated
6. ✅ Dry run tested
7. ✅ Code cleaned up

**To run the bot:**

```bash
# Dry run (no real orders)
python main.py --verbose

# Live trading
python main.py --live --verbose

# Check P&L
python main.py --check
```
