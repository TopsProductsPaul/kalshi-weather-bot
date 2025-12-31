#!/usr/bin/env python3
"""
Kalshi Weather Bot - Main Entry Point

Usage:
    python main.py              # Dry run, single pass
    python main.py --live       # Live trading, single pass
    python main.py --live --run # Live trading, continuous
    python main.py --check      # Check settlements and show P&L report
"""

import argparse
import sys
from datetime import datetime

from config import (
    KALSHI_API_KEY_ID,
    KALSHI_PRIVATE_KEY_PATH,
    KALSHI_ENV,
    TradingConfig,
    validate_config,
)
from clients import KalshiClient, NWSClient
from strategy import WeatherBotStrategy
from tracker import check_and_report


def main():
    parser = argparse.ArgumentParser(description="Kalshi Weather Trading Bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading (default: dry run)")
    parser.add_argument("--run", action="store_true", help="Run continuously (default: single pass)")
    parser.add_argument("--duration", type=int, help="Run duration in minutes (with --run)")
    parser.add_argument("--cities", nargs="+", help="Cities to trade (default: NYC)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--check", action="store_true", help="Check settlements and show P&L report")

    args = parser.parse_args()

    # Validate configuration
    try:
        validate_config()
    except ValueError as e:
        print(f"Configuration error:\n{e}")
        sys.exit(1)

    # Initialize clients
    print(f"Initializing Kalshi client ({KALSHI_ENV})...")
    kalshi = KalshiClient(
        key_id=KALSHI_API_KEY_ID,
        private_key_path=KALSHI_PRIVATE_KEY_PATH,
        env=KALSHI_ENV,
        verbose=args.verbose,
    )

    # Handle --check mode (settlement checking only)
    if args.check:
        check_and_report(kalshi)
        kalshi.close()
        return

    nws = NWSClient(verbose=args.verbose)

    # Check balance
    balance = kalshi.get_balance()
    print(f"Account balance: ${balance:.2f}")

    if balance < 10 and args.live:
        print("Warning: Low balance. Consider adding funds before live trading.")

    # Configure strategy
    cities = args.cities or TradingConfig.CITIES
    dry_run = not args.live

    print(f"\nMode: {'LIVE TRADING' if args.live else 'DRY RUN'}")
    print(f"Cities: {cities}")
    print(f"Min edge: {TradingConfig.MIN_EDGE_THRESHOLD * 100:.0f}%")
    print(f"Max daily risk: ${TradingConfig.MAX_DAILY_RISK:.0f}")
    print()

    # Create and run strategy
    bot = WeatherBotStrategy(
        kalshi=kalshi,
        nws=nws,
        cities=cities,
        min_edge=TradingConfig.MIN_EDGE_THRESHOLD,
        min_price=TradingConfig.MIN_YES_PRICE,
        max_price=TradingConfig.MAX_YES_PRICE,
        base_contracts=TradingConfig.BASE_POSITION_SIZE,
        dry_run=dry_run,
        check_interval=TradingConfig.CHECK_INTERVAL,
        max_daily_risk=TradingConfig.MAX_DAILY_RISK,
    )

    if args.run:
        # Continuous mode
        duration = args.duration or None
        print(f"Running continuously" + (f" for {duration} minutes" if duration else ""))
        print("Press Ctrl+C to stop\n")
        bot.run(duration_minutes=duration)
    else:
        # Single pass
        print("Running single pass...\n")
        bot.setup()
        bot.on_start()
        bot.on_tick()
        bot.on_stop()
        bot.cleanup()

    print("\nDone.")


if __name__ == "__main__":
    main()
