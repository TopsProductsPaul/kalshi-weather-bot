#!/usr/bin/env python3
"""
Kalshi BTC 15-Minute Hedged Bot

Note: This project runs in a virtual environment (.venv). All dependencies are installed.
      Activate with: source .venv/bin/activate

Trades EVERY 15-minute window with automatic hedging to cap losses.

Strategy:
  1. ENTRY (10-14 min before close): Enter based on initial momentum
  2. MONITOR (3-10 min before close): Hedge if price reverses
  3. HOLD (0-3 min before close): Let position ride to settlement

Usage:
    python btc_hedged_main.py              # Dry run, single pass
    python btc_hedged_main.py --live       # Live trading, single pass
    python btc_hedged_main.py --live --run # Live trading, continuous
"""

import argparse
import sys
from datetime import datetime

from config import (
    KALSHI_API_KEY_ID,
    KALSHI_PRIVATE_KEY_PATH,
    KALSHI_ENV,
    validate_config,
)
from clients import KalshiClient, BinanceClient
from strategy import BTCHedgedStrategy


def main():
    parser = argparse.ArgumentParser(description="Kalshi BTC 15-Minute Hedged Bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading")
    parser.add_argument("--run", action="store_true", help="Run continuously")
    parser.add_argument("--duration", type=int, help="Run duration in minutes")
    parser.add_argument("--interval", type=int, default=15, help="Check interval in seconds (default: 15)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    # Strategy parameters
    parser.add_argument("--contracts", type=int, default=10, help="Contracts per trade (default: 10)")
    parser.add_argument("--max-price", type=int, default=55, help="Max entry price in cents (default: 55)")
    parser.add_argument("--min-change", type=float, default=0.05, help="Min %% change to enter (default: 0.05)")
    parser.add_argument("--hedge-trigger", type=float, default=0.25, help="Reversal %% to trigger hedge (default: 0.25)")
    parser.add_argument("--min-edge", type=float, default=5.0, help="Min edge %% to enter (default: 5.0)")
    parser.add_argument("--no-limit-orders", action="store_true", help="Disable limit orders (use market-taking)")
    
    # Timing windows
    parser.add_argument("--entry-start", type=int, default=14, help="Start entry window N min before close (default: 14)")
    parser.add_argument("--entry-end", type=int, default=10, help="End entry window N min before close (default: 10)")
    parser.add_argument("--hedge-start", type=int, default=10, help="Start hedge window N min before close (default: 10)")
    parser.add_argument("--hedge-end", type=int, default=3, help="End hedge window N min before close (default: 3)")

    args = parser.parse_args()

    # Validate configuration
    try:
        validate_config()
    except ValueError as e:
        print(f"Configuration error:\n{e}")
        sys.exit(1)

    # Initialize Kalshi client
    print(f"Initializing Kalshi client ({KALSHI_ENV})...")
    kalshi = KalshiClient(
        key_id=KALSHI_API_KEY_ID,
        private_key_path=KALSHI_PRIVATE_KEY_PATH,
        env=KALSHI_ENV,
        verbose=args.verbose,
    )

    # Check balance
    balance = kalshi.get_balance()
    print(f"Account balance: ${balance:.2f}")

    if balance < 10 and args.live:
        print("Warning: Low balance.")

    # Configure strategy
    dry_run = not args.live

    print(f"\nMode: {'LIVE TRADING' if args.live else 'DRY RUN'}")
    print(f"Contracts per trade: {args.contracts}")
    print(f"Max entry price: {args.max_price}¢")
    print(f"Entry window: {args.entry_start}-{args.entry_end} min before close")
    print(f"Hedge window: {args.hedge_start}-{args.hedge_end} min before close")
    print(f"Min entry change: {args.min_change}%")
    print(f"Hedge trigger: {args.hedge_trigger}% reversal")
    print(f"Min edge: {args.min_edge}%")
    print(f"Limit orders: {not args.no_limit_orders}")
    print()

    # Create and run strategy
    bot = BTCHedgedStrategy(
        kalshi=kalshi,
        base_contracts=args.contracts,
        hedge_contracts=args.contracts,
        max_price=args.max_price,
        entry_window_start=args.entry_start,
        entry_window_end=args.entry_end,
        hedge_window_start=args.hedge_start,
        hedge_window_end=args.hedge_end,
        min_entry_change=args.min_change,
        hedge_trigger_pct=args.hedge_trigger,
        min_edge_pct=args.min_edge,
        use_limit_orders=not args.no_limit_orders,
        dry_run=dry_run,
        check_interval=args.interval,
        max_daily_risk=200.0,
    )

    if args.run:
        duration = args.duration or None
        print(f"Running continuously" + (f" for {duration} minutes" if duration else ""))
        print("Press Ctrl+C to stop\n")
        bot.run(duration_minutes=duration)
    else:
        print("Running single pass...\n")
        bot.setup()
        bot.on_start()
        bot.on_tick()
        bot.on_stop()
        bot.cleanup()

    print("\nDone.")


if __name__ == "__main__":
    main()
