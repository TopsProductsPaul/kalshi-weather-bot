"""Configuration settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# Kalshi API
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "./kalshi_private_key.pem")
KALSHI_ENV = os.getenv("KALSHI_ENV", "demo")  # "demo" or "prod"


# Trading parameters
class TradingConfig:
    # Position sizing (conservative for testing)
    BASE_POSITION_SIZE = 3        # contracts per trade (small bets)
    MAX_POSITION_PER_MARKET = 20  # max contracts in single market
    MAX_DAILY_RISK = 10.0         # max $ at risk per day (hard cap)

    # Edge thresholds
    MIN_EDGE_THRESHOLD = 0.05     # 5% minimum edge to trade
    MIN_YES_PRICE = 10            # don't buy YES below 10¢
    MAX_YES_PRICE = 50            # don't buy YES above 50¢

    # Cities to trade (start with one)
    CITIES = ["NYC"]

    # Timing
    CHECK_INTERVAL = 300          # seconds between checks (5 min)


# Validate config
def validate_config():
    """Ensure required config is present."""
    errors = []

    if not KALSHI_API_KEY_ID:
        errors.append("KALSHI_API_KEY_ID not set in .env")

    key_path = Path(KALSHI_PRIVATE_KEY_PATH)
    if not key_path.exists():
        errors.append(f"Private key not found at {KALSHI_PRIVATE_KEY_PATH}")

    if errors:
        raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))

    return True
