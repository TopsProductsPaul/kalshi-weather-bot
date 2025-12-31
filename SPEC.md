# Kalshi Weather Bot Specification

## Intent

A trading bot that exploits mispriced temperature buckets on Kalshi weather markets.

**Edge source**: Weather forecasts (NWS, ensemble models) are more accurate than market-implied probabilities. When our forecast confidence exceeds market pricing, we have positive expected value.

**Target markets**: Daily high/low temperature markets across 8 US cities:

| Series | City | Station |
|--------|------|---------|
| `KXHIGHNY` | NYC | Central Park |
| `KXHIGHCHI` | Chicago | Midway Airport |
| `KXHIGHMIA` | Miami | MIA Airport |
| `KXHIGHAUS` | Austin | Bergstrom Airport |
| `KXHIGHDEN` | Denver | Denver |
| `KXHIGHHOU` | Houston | Houston |
| `KXHIGHLAX` | Los Angeles | LAX |
| `KXHIGHPHIL` | Philadelphia | Philadelphia |

Low temperature markets also available (`KXLOW{CITY}`).

**Settlement**: National Weather Service Daily Climate Report (next morning)

---

## Market Structure (Research Findings)

Each daily temperature event has **6 markets**:

| Type | Example Ticker | Description |
|------|----------------|-------------|
| Tail Low | `KXHIGHLAX-25DEC30-T68` | Temperature < 68°F |
| Bucket | `KXHIGHLAX-25DEC30-B68.5` | Temperature 68-69°F |
| Bucket | `KXHIGHLAX-25DEC30-B70.5` | Temperature 70-71°F |
| Bucket | `KXHIGHLAX-25DEC30-B72.5` | Temperature 72-73°F |
| Bucket | `KXHIGHLAX-25DEC30-B74.5` | Temperature 74-75°F |
| Tail High | `KXHIGHLAX-25DEC30-T75` | Temperature > 75°F |

**Ticker format**: `KX{HIGH/LOW}{CITY}-{YY}{MMM}{DD}-{B/T}{temp}`

**Bucket width**: 2 degrees Fahrenheit

**Typical volume**: 30,000 - 70,000 contracts per bucket

---

## Strategy

### Core Logic

```
1. Fetch tomorrow's temperature markets from Kalshi
2. Generate probability distribution from weather forecasts
3. Compare model probabilities vs market prices
4. Buy YES on buckets where: model_prob > market_price + MIN_EDGE
5. Size positions by edge magnitude, capped by risk limits
```

### Edge Calculation

```python
edge = model_probability - (market_yes_price / 100)
expected_value = (model_prob * payout) - ((1 - model_prob) * cost)

# Only trade when edge exceeds threshold
if edge > MIN_EDGE_THRESHOLD:
    position_size = base_size * (edge / MIN_EDGE_THRESHOLD)
```

### Position Types

| Type | When | Action |
|------|------|--------|
| Single bucket | High confidence (>70%) in narrow range | Buy YES |
| Cluster | Moderate confidence across adjacent buckets | Buy YES on 2-3 buckets |
| Fade extreme | Tail bucket overpriced vs forecast | Sell YES (buy NO) |

---

## Architecture

```
kalshi-weather-bot/
├── config.py              # Settings, risk parameters
├── main.py                # Entry point
│
├── models/                # Data structures (dataclasses)
│   ├── market.py          # Market, Bucket, Event
│   ├── order.py           # Order, OrderSide, OrderStatus
│   └── forecast.py        # Forecast, ProbabilityDist
│
├── clients/               # API clients
│   ├── base.py            # Base client (rate limit, retry)
│   ├── kalshi.py          # Kalshi API wrapper
│   └── nws.py             # NWS weather API
│
├── strategy/              # Trading logic
│   ├── base.py            # Strategy base class (lifecycle hooks)
│   ├── forecast.py        # NWS → probability distribution
│   ├── edge.py            # Edge calculator
│   └── weather_bot.py     # Main strategy implementation
│
├── errors.py              # Exception hierarchy
└── utils.py               # Helpers, logging
```

Inspired by [dr-manhattan](https://github.com/guzus/dr-manhattan) patterns:
- Dataclasses with properties for models
- Base client with rate limiting + exponential backoff retry
- Strategy lifecycle hooks (setup → on_start → on_tick → on_stop)
- Hierarchical error classes

### Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Ingest    │ ──▶ │  Forecast   │ ──▶ │    Edge     │ ──▶ │   Execute   │
│             │     │             │     │             │     │             │
│ • Kalshi    │     │ • NWS data  │     │ • Compare   │     │ • Place     │
│   markets   │     │ • Build     │     │   model vs  │     │   orders    │
│ • Weather   │     │   prob      │     │   market    │     │ • Track     │
│   forecasts │     │   dist      │     │ • Size      │     │   fills     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

---

## Configuration

### Risk Parameters

```python
# config.py

# Position sizing
BASE_POSITION_SIZE = 10      # contracts per trade
MAX_POSITION_PER_MARKET = 50 # max contracts in single market
MAX_DAILY_RISK = 100         # max $ at risk per day

# Edge thresholds
MIN_EDGE_THRESHOLD = 0.05    # 5% minimum edge to trade
MIN_YES_PRICE = 0.10         # don't buy YES below 10¢
MAX_YES_PRICE = 0.50         # don't buy YES above 50¢

# Bucket filters
MAX_BUCKET_WIDTH = 10        # max temperature range (°F)
```

### API Configuration

```python
# .env file
KALSHI_API_KEY_ID=your-key-id-uuid
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem
KALSHI_ENV=demo  # "demo" or "prod"

# API URLs
PROD_URL = "https://api.elections.kalshi.com"
DEMO_URL = "https://demo-api.kalshi.co"
```

Authentication uses RSA-PSS signing (see `explore_markets.py` for implementation).

---

## Key Interfaces

### Market Data (Kalshi)

```python
class KalshiClient:
    def get_weather_markets(self, city: str, date: str) -> list[Market]
    def get_orderbook(self, ticker: str) -> Orderbook
    def place_order(self, order: Order) -> OrderResult
    def get_positions(self) -> list[Position]
```

### Weather Data (NWS)

```python
class WeatherClient:
    def get_forecast(self, station: str) -> Forecast
    def get_historical(self, station: str, days: int) -> list[Observation]
```

### Strategy

```python
class ForecastModel:
    def predict(self, city: str, date: str) -> ProbabilityDistribution
    # Returns: {temp_range: probability} for each bucket

class EdgeCalculator:
    def calculate(self, forecast: ProbabilityDistribution, markets: list[Market]) -> list[Edge]
    # Returns: list of (market, edge, expected_value)

class PositionBuilder:
    def build(self, edges: list[Edge]) -> list[Position]
    # Returns: sized positions respecting risk limits
```

---

## Operational Flow

### Daily Schedule

```
06:00  Fetch next-day weather markets
06:05  Pull latest NWS forecasts
06:10  Generate probability distribution
06:15  Calculate edges, build positions
06:20  Execute trades
12:00  Re-evaluate with updated forecasts (optional)
18:00  Final position adjustments before market close

Next morning:
07:00  Check NWS Daily Climate Report
07:05  Reconcile P&L
```

### Logging

Every trade logged with:
- Timestamp
- Market ticker
- Model probability vs market price
- Edge and expected value
- Position size
- Fill price

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Win rate | > 60% |
| Average edge per trade | > 5% |
| Sharpe ratio | > 1.5 |
| Max drawdown | < 20% of bankroll |

---

## Phase 1 Scope (MVP)

1. **Single city**: NYC only
2. **Simple forecast**: NWS point forecast → normal distribution
3. **Basic execution**: Market orders only
4. **Manual trigger**: Run script manually, no scheduler

### MVP Excludes
- Multi-city optimization
- Ensemble forecasting
- Limit order management
- Automated scheduling
- Real-time position monitoring

---

## Dependencies

```
httpx          # HTTP client for APIs
pydantic       # Data validation
python-dotenv  # Environment variables
loguru         # Logging
```

---

## References

- [Kalshi API Docs](https://docs.kalshi.com)
- [Kalshi Weather Markets](https://help.kalshi.com/markets/popular-markets/weather-markets)
- [NWS API](https://www.weather.gov/documentation/services-web-api)
- [Dr-Manhattan](https://github.com/guzus/dr-manhattan) - Prediction market framework (weather bot discussion in issue #45)
