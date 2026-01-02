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

# xAI API (for Grok models)
XAI_API_KEY = os.getenv("XAI_API_KEY")


# Trading parameters
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
