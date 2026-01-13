#!/usr/bin/env python3
"""
Analyze forecast edge for weather markets.

Shows where NWS forecast disagrees with market prices.
No orders placed - analysis only.

Usage:
    python analyze_edge.py
    python analyze_edge.py --city NYC
    python analyze_edge.py --days 2
"""

import argparse
from datetime import datetime, timedelta

from config import (
    KALSHI_API_KEY_ID,
    KALSHI_PRIVATE_KEY_PATH,
    KALSHI_ENV,
    TradingConfig,
    validate_config,
)
from clients import KalshiClient, NWSClient
from strategy.spread_selector import calculate_bucket_edges, select_spread_with_edge


def analyze_city(kalshi: KalshiClient, nws: NWSClient, city: str, target_date: datetime):
    """Analyze a single city for edge opportunities."""
    
    print(f"\n{'='*60}")
    print(f"{city} - {target_date.date()}")
    print('='*60)
    
    # 1. Get market
    market = kalshi.get_weather_market(city, target_date, "HIGH")
    if not market:
        print(f"  No market found")
        return
    
    if not market.is_open:
        print(f"  Market closed")
        return
    
    # 2. Get forecast
    try:
        forecast = nws.get_forecast(city, target_date)
    except Exception as e:
        print(f"  Forecast error: {e}")
        return
    
    if not forecast:
        print(f"  No forecast available")
        return
    
    print(f"\nNWS Forecast: {forecast.high_temp}°F (±{forecast.high_temp_std}°F)")
    
    # 3. Find market-implied temperature (bucket with highest price)
    peak_bucket = max(market.buckets, key=lambda b: b.yes_bid)
    market_implied = (peak_bucket.temp_min + peak_bucket.temp_max) / 2 if peak_bucket.temp_min and peak_bucket.temp_max else "?"
    print(f"Market implies: ~{market_implied}°F (peak bucket: {peak_bucket.yes_bid}¢)")
    
    diff = forecast.high_temp - market_implied if isinstance(market_implied, (int, float)) else 0
    print(f"Difference: {diff:+.1f}°F")
    
    # 4. Calculate edges
    edges = calculate_bucket_edges(market, forecast)
    
    print(f"\nEdge Analysis (positive = we think more likely than market):")
    print("-" * 60)
    print(f"{'Bucket':<15} {'Forecast':<12} {'Market':<12} {'Edge':<10} {'EV':<10}")
    print("-" * 60)
    
    for e in edges:
        edge_color = "" if e.edge <= 0 else "→"
        print(f"{e.bucket_range:<15} {e.model_prob*100:>6.1f}%     {e.market_prob*100:>6.1f}%     {e.edge*100:>+6.1f}%    {e.expected_value:>+6.1f}¢  {edge_color}")
    
    # 5. Best opportunity
    spread, _ = select_spread_with_edge(market, forecast, min_edge=0.05)
    
    print("\n" + "-" * 60)
    if spread:
        print(f"OPPORTUNITY: {spread.range_str}")
        print(f"  Cost: {spread.total_cost}¢, Potential profit: +{spread.potential_profit}¢")
        for b in spread.buckets:
            edge = next((e for e in edges if e.bucket_ticker == b.ticker), None)
            if edge:
                print(f"    {b.ticker}: {edge.edge*100:+.1f}% edge, EV: {edge.expected_value:+.1f}¢")
    else:
        print("NO OPPORTUNITY: No buckets with ≥5% edge")


def main():
    parser = argparse.ArgumentParser(description="Analyze weather market edge")
    parser.add_argument("--city", help="Single city to analyze")
    parser.add_argument("--days", type=int, default=1, help="Days ahead (default: 1 = tomorrow)")
    args = parser.parse_args()
    
    # Validate config
    try:
        validate_config()
    except ValueError as e:
        print(f"Config error: {e}")
        return
    
    # Initialize clients
    print("Initializing clients...")
    kalshi = KalshiClient(
        key_id=KALSHI_API_KEY_ID,
        private_key_path=KALSHI_PRIVATE_KEY_PATH,
        env=KALSHI_ENV,
    )
    nws = NWSClient()
    
    target_date = datetime.now() + timedelta(days=args.days)
    
    cities = [args.city.upper()] if args.city else TradingConfig.CITIES
    
    print(f"\nAnalyzing {len(cities)} cities for {target_date.date()}...")
    
    for city in cities:
        try:
            analyze_city(kalshi, nws, city, target_date)
        except Exception as e:
            print(f"\n{city}: Error - {e}")
    
    print("\n" + "="*60)
    print("Analysis complete. No orders placed.")
    
    kalshi.close()


if __name__ == "__main__":
    main()
