"""
Explore available weather markets on Kalshi.
Run this to see what's actually tradeable.
"""

import os
import time
import base64
import httpx
from pathlib import Path
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv()

# Config
KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "./kalshi_private_key.pem")
ENV = os.getenv("KALSHI_ENV", "demo")

# Override to check prod markets (read-only is fine)
BASE_URL = "https://api.elections.kalshi.com"  # prod has the real markets


def load_private_key():
    key_path = Path(KEY_PATH)
    if not key_path.exists():
        raise FileNotFoundError(f"Private key not found at {KEY_PATH}")

    with open(key_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def sign_request(private_key, timestamp: str, method: str, path: str) -> str:
    """Sign request using RSA-PSS."""
    message = f"{timestamp}{method}{path}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode("utf-8")


def get_headers(private_key, method: str, path: str) -> dict:
    """Generate authentication headers."""
    timestamp = str(int(time.time() * 1000))
    signature = sign_request(private_key, timestamp, method, path)

    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }


def main():
    print(f"Connecting to Kalshi ({ENV})...")
    print(f"Base URL: {BASE_URL}")
    print(f"Key ID: {KEY_ID[:8]}...")
    print()

    private_key = load_private_key()

    # Search for weather-related events
    path = "/trade-api/v2/events"
    headers = get_headers(private_key, "GET", path)

    with httpx.Client() as client:
        # Get all events, we'll filter for weather
        response = client.get(
            f"{BASE_URL}{path}",
            headers=headers,
            params={"limit": 200, "status": "open"}
        )

        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            print(response.text)
            return

        data = response.json()
        events = data.get("events", [])

        # Filter for weather-related events
        weather_keywords = ["temperature", "weather", "high", "low", "rain", "snow", "heat"]
        weather_events = []

        for event in events:
            title = event.get("title", "").lower()
            category = event.get("category", "").lower()

            if any(kw in title for kw in weather_keywords) or "weather" in category:
                weather_events.append(event)

        print(f"Found {len(weather_events)} weather-related events:\n")
        print("=" * 80)

        for event in weather_events[:20]:  # Show first 20
            print(f"Title: {event.get('title')}")
            print(f"Ticker: {event.get('event_ticker')}")
            print(f"Category: {event.get('category')}")
            print(f"Series: {event.get('series_ticker')}")
            print(f"Markets: {event.get('mutually_exclusive', 'N/A')}")
            print("-" * 40)

        # Also search for series (market groups)
        print("\n\nSearching for weather series...")
        series_path = "/trade-api/v2/series"
        headers = get_headers(private_key, "GET", series_path)

        response = client.get(
            f"{BASE_URL}{series_path}",
            headers=headers
        )

        if response.status_code == 200:
            series_data = response.json()
            series_list = series_data.get("series", [])

            weather_series = [s for s in series_list
                             if any(kw in s.get("title", "").lower() for kw in weather_keywords)]

            # Look specifically for daily high/low temp markets
            temp_series = [s for s in series_list
                          if any(x in s.get("ticker", "").upper() for x in ["HIGH", "LOW", "TEMP"])]

            print("=== TEMPERATURE SERIES ===")
            for s in sorted(temp_series, key=lambda x: x.get("ticker", "")):
                print(f"  {s.get('ticker')}: {s.get('title')}")

            print(f"\n=== ALL WEATHER SERIES ({len(weather_series)} total, showing 30) ===")
            for s in weather_series[:30]:
                print(f"  {s.get('ticker')}: {s.get('title')}")

        # Search all open markets for temperature-related ones
        print("\n\n=== SEARCHING ALL OPEN MARKETS FOR TEMPERATURE ===")
        markets_path = "/trade-api/v2/markets"
        headers = get_headers(private_key, "GET", markets_path)

        response = client.get(
            f"{BASE_URL}{markets_path}",
            headers=headers,
            params={"status": "open", "limit": 1000}
        )

        if response.status_code == 200:
            all_markets = response.json().get("markets", [])
            print(f"Total open markets: {len(all_markets)}")

            # Search for weather patterns in tickers
            weather_patterns = ["RAIN", "SNOW", "TEMP", "HIGH", "LOW", "WEATHER"]
            weather_markets = [m for m in all_markets
                              if any(p in m.get("ticker", "").upper() for p in weather_patterns)]

            print(f"\nWeather-related markets (patterns: {weather_patterns}):")
            print(f"Found: {len(weather_markets)}")
            for m in weather_markets[:30]:
                print(f"  {m.get('ticker')}: {m.get('subtitle', m.get('title', ''))[:60]}")

        # Check events with various statuses
        print("\n\n=== CHECKING EVENTS BY STATUS ===")
        for status in ["open", "unopened", "closed"]:
            events_path = "/trade-api/v2/events"
            headers = get_headers(private_key, "GET", events_path)
            response = client.get(
                f"{BASE_URL}{events_path}",
                headers=headers,
                params={"status": status, "limit": 200}
            )
            if response.status_code == 200:
                events = response.json().get("events", [])
                weather_events = [e for e in events
                                 if any(x in e.get("title", "").lower()
                                       for x in ["temperature", "weather", "rain", "snow"])]
                print(f"\n{status.upper()} weather events: {len(weather_events)}")
                for e in weather_events[:5]:
                    print(f"  {e.get('event_ticker')}: {e.get('title')[:50]}")

        # Get markets for a specific closed weather event to see bucket structure
        print("\n\n=== BUCKET STRUCTURE (from recent closed event) ===")
        markets_path = "/trade-api/v2/markets"
        headers = get_headers(private_key, "GET", markets_path)

        # Try to get LA high temp markets from Dec 30
        response = client.get(
            f"{BASE_URL}{markets_path}",
            headers=headers,
            params={"event_ticker": "KXHIGHLAX-25DEC30", "limit": 50}
        )

        if response.status_code == 200:
            markets = response.json().get("markets", [])
            print(f"Found {len(markets)} buckets for KXHIGHLAX-25DEC30:\n")

            for m in sorted(markets, key=lambda x: x.get("ticker", "")):
                ticker = m.get("ticker", "")
                subtitle = m.get("subtitle", "") or m.get("title", "")
                result = m.get("result", "")
                yes_bid = m.get("yes_bid") or 0
                yes_ask = m.get("yes_ask") or 0
                volume = m.get("volume", 0)

                print(f"{ticker}")
                print(f"  Range: {subtitle}")
                print(f"  Result: {result} | Volume: {volume}")
                print()


if __name__ == "__main__":
    main()
