# Bucket Spread Strategy Design

## Overview

Replace the forecast-based edge strategy with a simpler bucket spread approach inspired by [Dr-Manhattan issue #45](https://github.com/guzus/dr-manhattan/issues/45).

**Core insight:** Buy 2 adjacent temperature buckets around the peak. One pays $1, covering the cost of both. No weather forecast needed.

## Strategy

### How It Works

1. Fetch tomorrow's temperature markets from Kalshi
2. Find the "peak" bucket (highest bid price = most likely outcome)
3. Buy peak + 1 neighbor using limit orders at bid price
4. Total cost must be < 95¢ (since payout is $1)
5. If temp lands in either bucket, profit = $1 - cost

### Example Trade

```
NYC High Temp - Jan 2, 2026

Peak: 30-31°F @ 49¢ bid
Neighbor: 32-33°F @ 33¢ bid

Buy 10 contracts each:
  10 × 49¢ = $4.90
  10 × 33¢ = $3.30
  Total: $8.20

If temp is 30-33°F → one bucket pays $10 → profit $1.80
If temp outside → lose $8.20
```

### Why This Works

- Market prices already reflect probability (no forecast needed)
- Peak + neighbor covers ~60-80% of outcomes
- Limit orders at bid get better pricing than market orders
- 2 buckets keeps total cost safely under $1

## Configuration

```python
# config.py

# Bucket spread strategy
MIN_BUCKET_PRICE = 10         # Don't buy below 10¢ (too unlikely)
MAX_BUCKET_PRICE = 60         # Allow up to 60¢ (peaks are 35-57¢)
MAX_BUCKETS = 2               # Prevents >100¢ cost
MAX_TOTAL_COST = 95           # Safety cap (¢)
CONTRACTS_PER_BUCKET = 10     # Fixed size per bucket
USE_LIMIT_ORDERS = True       # Buy at bid, not ask
MAX_DAILY_COST = 100          # Total $ to deploy per day

# Cities (LA and Chicago have better spreads)
CITIES = ["LA", "CHICAGO", "NYC", "MIAMI"]
```

## Algorithm

```
on_tick():
    for city in CITIES:
        1. GET MARKETS
           → Fetch tomorrow's temperature buckets
           → Filter: only open markets

        2. FIND PEAK
           → Sort by bid price (highest = most likely)
           → Peak must be in 10-60¢ range

        3. SELECT NEIGHBOR
           → Check left and right neighbors
           → Pick the one where peak + neighbor < 95¢
           → Prefer higher bid price if both qualify

        4. VALIDATE
           → Total cost < MAX_TOTAL_COST?
           → Not already holding this market?
           → Daily limit not exceeded?

        5. PLACE LIMIT ORDERS
           → Order at bid price for each bucket
           → Track order IDs

        6. LOG
           → "NYC 30-33°F: 2 buckets @ 82¢"
```

## Market Research (Jan 2, 2026)

### Bucket Structure

Each city has 6 buckets: 2 tails + 4 middle buckets spanning ~8°F.

### Pricing Reality

| City | Peak Bucket | Bid | Ask | 2-Bucket Cost (Ask) |
|------|-------------|-----|-----|---------------------|
| NYC | 30-31°F | 49¢ | 56¢ | 90¢ |
| LA | 68-69°F | 37¢ | 43¢ | 83¢ |
| Chicago | 26-27°F | 35¢ | 45¢ | 77¢ |
| Miami | 73-74°F | 53¢ | 57¢ | 99¢ |

### Key Finding

3-bucket spreads at ask prices can exceed 100¢ = guaranteed loss:
- NYC: 106¢ (-6¢ loss)
- Miami: 110¢ (-10¢ loss)

Solution: Limit to 2 buckets, use limit orders at bid.

## Files to Change

### Modify

| File | Changes |
|------|---------|
| `config.py` | Replace edge params with spread params |
| `strategy/weather_bot.py` | New `on_tick()` with spread logic |

### Remove/Simplify

| Code | Reason |
|------|--------|
| `_forecast_to_distribution()` | No longer needed |
| `_calculate_edges()` | Replaced by spread selection |
| Edge/probability classes in models | Not used |

### Keep

| File | Reason |
|------|--------|
| `clients/kalshi.py` | Still fetching markets and placing orders |
| `tracker.py` | Still tracking P&L |
| `main.py` | Entry point unchanged |

## Order Execution

### Limit Order Flow

1. Fetch orderbook (yes_bid, yes_ask)
2. Place limit order at yes_bid price
3. Check fill status before market close
4. Record filled trades in tracker

### Order States

| Status | Action |
|--------|--------|
| Filled | Record trade |
| Partial | Track filled qty |
| Unfilled | Cancel or leave (configurable) |

## Edge Cases

| Scenario | Handling |
|----------|----------|
| No buckets in 10-60¢ range | Skip market |
| Peak + neighbor > 95¢ | Try other neighbor, or skip |
| Only 1 bucket qualifies | Buy single bucket |
| Already traded this market | Skip |
| Daily limit reached | Stop trading |
| Order doesn't fill | Log, continue |

## Success Metrics

| Metric | Target |
|--------|--------|
| Win rate | > 65% |
| Avg profit per win | ~15-20¢ per contract |
| Max spread cost | < 95¢ |

## What's Removed

- NWS forecast fetching (optional to keep for logging)
- Probability distribution calculation
- Edge threshold logic
- Expected value calculations

## Next Steps

1. Update `config.py` with new parameters
2. Rewrite `WeatherBotStrategy.on_tick()` with spread logic
3. Add limit order support to Kalshi client (if not present)
4. Test on demo account
5. Run paper trading for 1 week before live
