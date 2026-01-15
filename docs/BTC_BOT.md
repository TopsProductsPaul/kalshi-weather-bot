# BTC 15-Minute Trading Bot

## Overview

The BTC bot trades Kalshi's 15-minute BTC price prediction markets (`KXBTC15M`). These binary markets settle based on whether BTC's price goes **up or down** within a 15-minute window.

**Edge Source**: BTC price momentum near window close. If BTC has moved significantly in one direction with little time left, the outcome is nearly certain but may not be fully priced in.

---

## Market Structure

### Ticker Format
```
KXBTC15M-{YY}{MMM}{DD}{HHMM}-{MM}
         │    │    │    │      └── Window end minute (:00, :15, :30, :45)
         │    │    │    └── Window end time (HHMM UTC)
         │    │    └── Day
         │    └── Month
         └── Year
```

**Example**: `KXBTC15M-26JAN151030-30`
- Date: January 15, 2026
- Window ends at 10:30 UTC
- Market: "BTC up in next 15 mins" starting at 10:15 UTC

### Settlement
- **YES wins**: BTC price at window end > BTC price at window start
- **NO wins**: BTC price at window end ≤ BTC price at window start

---

## Strategy

### Core Logic

```
1. Find active 15-minute window (2-15 min before close)
2. Get BTC price at window start (from Binance klines)
3. Get current BTC price
4. Calculate % change and confidence
5. If confidence > threshold, bet on expected direction
6. Scale position size by confidence level
```

### Confidence Calculation

```python
# Base confidence from price change magnitude
price_confidence = 0.5 + (abs(pct_change) * 0.4)  # capped at 0.95

# Time factor (closer to close = higher confidence)
time_factor = 1 - (minutes_left / 15)

# Combined
confidence = price_confidence * (0.5 + 0.5 * time_factor)

# Bonuses
if momentum_confirmed:  confidence += 0.15
if abs(pct_change) >= 0.15:  confidence += 0.10
```

### Trade Execution Logic

**When price is UP** (want YES to win):
1. **BUY YES** at `yes_ask` if ≤ max_price
2. Fallback: **SELL NO** at `no_bid` if risk acceptable

**When price is DOWN** (want NO to win):
1. **SELL YES** at `yes_bid` (effectively buying NO)
2. Fallback: High-confidence SELL YES at low bids

---

## CLI Parameters

```bash
python btc_main.py [OPTIONS]
```

### Modes
| Flag | Description |
|------|-------------|
| `--live` | Enable live trading (default: dry run) |
| `--run` | Run continuously (default: single pass) |
| `--monitor` | Just show market status, no trading |
| `--verbose` | Verbose logging |

### Strategy Tuning
| Parameter | Default | Description |
|-----------|---------|-------------|
| `--confidence` | 0.65 | Minimum confidence to bet (0-1) |
| `--window` | 10 | Start betting N minutes before close |
| `--min-window` | 2 | Stop betting N minutes before close |
| `--min-change` | 0.05 | Minimum % price change to consider |
| `--max-price` | 95 | Max price to pay in cents |
| `--contracts` | 10 | Max contracts per bet |
| `--min-contracts` | 2 | Min contracts per bet |
| `--no-scale` | false | Disable confidence-based scaling |

### Timing
| Parameter | Default | Description |
|-----------|---------|-------------|
| `--interval` | 30 | Check interval in seconds |
| `--duration` | ∞ | Run duration in minutes |

---

## Example Commands

### Conservative (Default)
```bash
python btc_main.py --live --run --interval 30
# 65% confidence, 95¢ max, 2-10 contracts
```

### Aggressive High-Volume
```bash
python btc_main.py --live --run --interval 5 \
  --min-contracts 30 --contracts 50 \
  --confidence 0.60 --window 15 --max-price 98
```

### Experimental Low-Entry
```bash
python btc_main.py --live --run --interval 5 \
  --min-contracts 1 --contracts 5 \
  --confidence 0.50 --window 15 --max-price 80
```

---

## Session Performance

### January 15, 2026 Session (Morning)

**Parameters**: `--confidence 0.60 --max-price 98 --contracts 50 --min-contracts 30`

| Stat | Value |
|------|-------|
| Duration | ~3 hours |
| Trades Executed | 2 |
| Win Rate | 100% |
| P&L | +$10.22 |
| Starting Balance | $296.28 |
| Ending Balance | $331.70 |

**Observations**:
- Most windows skipped due to: price change < 0.05%, confidence < 60%
- Efficient markets: by the time signal is clear, prices already reflect it

---

## Key Insights

### Market Efficiency Challenge
When BTC moves significantly, market makers quickly adjust:
- **UP move**: YES ask jumps to 95-99¢ (too expensive)
- **DOWN move**: YES bid drops to 1-3¢ (low premium to sell)

**Result**: Profitable entry points are rare.

### What Works
1. **SELL YES on down moves** - receive premium, keep it if NO wins
2. **Larger positions** - more profit per opportunity (when found)
3. **Lower intervals** - catch brief inefficiencies

### What Doesn't Work
1. **Low max-price with high confidence** - miss all trades
2. **Waiting too long** - prices already efficient by close

---

## Improvement Ideas

### 1. Hedging Strategy
When placing a directional bet:
- Simultaneously place opposite bet at extreme price
- Example: BUY YES @ 85¢, also BUY NO @ 10¢
- Caps max loss, reduces expected value

### 2. Spread Trading
Instead of picking direction:
- SELL both YES and NO at mid prices
- Profit if market stays relatively flat
- Risk: large moves in either direction

### 3. Multi-Window Tracking
- Track momentum across consecutive 15-min windows
- If 3+ windows trend same direction, higher confidence
- Bet on continuation in next window

### 4. Volatility Filtering
- Skip periods of low BTC volatility (< 0.1% moves)
- Target high-vol periods (news events, US market hours)

### 5. Dynamic Pricing
Instead of fixed max-price:
```python
# Scale acceptable price by confidence
adjusted_max = base_max * (0.8 + 0.2 * confidence)
# 80% conf → 96¢, 60% conf → 92¢
```

---

## File Structure

```
kalshi-weather-bot/
├── btc_main.py              # BTC bot entry point
├── strategy/
│   ├── base.py              # Strategy base class
│   └── btc_bot.py           # BTCBotStrategy implementation
├── clients/
│   ├── kalshi.py            # Kalshi API client
│   └── crypto.py            # Binance price client
├── trades.json              # Trade history
├── btc_bot.log              # Detailed logs
└── docs/
    └── BTC_BOT.md           # This file
```

---

## Trade History Schema

```json
{
  "ticker": "KXBTC15M-26JAN150945-45",
  "contracts": 33,
  "price": 8,
  "side": "sell",
  "placed_at": "2026-01-15T09:35:30.640239",
  "cost": 2.64,
  "settled": false,
  "settled_at": null,
  "result": null,
  "payout": 0.0,
  "pnl": 0.0
}
```

---

## Risk Management

### Built-in Controls
- `max_daily_risk`: Cap total daily exposure (default: $100)
- `max_price`: Never pay more than N cents
- `min_confidence`: Skip uncertain opportunities

### Manual Controls
- Review `trades.json` for position exposure
- Use `--monitor` to observe without trading
- Start with `--dry-run` to test parameters

---

## Troubleshooting

### "No active BTC 15M market found"
Markets only exist during active windows. Check timing.

### "Price change too small"
BTC hasn't moved enough. Lower `--min-change` or wait.

### "Confidence too low"
Increase `--window` to enter earlier, or lower `--confidence` threshold.

### "No viable trade"
Market already priced efficiently. Lower `--max-price` to be more selective, or increase to accept more risk.
