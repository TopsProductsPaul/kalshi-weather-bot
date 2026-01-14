#!/usr/bin/env python3
"""
Kalshi BTC 15-Minute Bot - Main Entry Point

Monitors BTC 15-minute up/down markets and bets on near-certain outcomes.

Usage:
    python btc_main.py              # Dry run, single pass
    python btc_main.py --live       # Live trading, single pass
    python btc_main.py --live --run # Live trading, continuous
    python btc_main.py --monitor    # Just monitor markets (no trading)
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
from strategy import BTCBotStrategy


def monitor_markets(kalshi: KalshiClient):
    """Monitor mode - just show market status without trading."""
    print("=== BTC 15M Market Monitor ===\n")

    # Get BTC price
    crypto = BinanceClient()
    btc_price = crypto.get_btc_price()
    print(f"Current BTC: ${btc_price:,.2f}\n")

    # Check for active markets
    print("Checking for active BTC 15M markets...")
    market = kalshi.get_active_btc_market()

    if market:
        ticker = market.get("ticker", "")
        yes_bid = market.get("yes_bid") or 0
        yes_ask = market.get("yes_ask") or 100
        volume = market.get("volume", 0)
        close_time = market.get("close_time", "")

        print(f"\n✅ ACTIVE MARKET FOUND:")
        print(f"  Ticker: {ticker}")
        print(f"  YES Bid/Ask: {yes_bid}/{yes_ask}¢")
        print(f"  Volume: {volume}")
        print(f"  Closes: {close_time}")
    else:
        print("\n❌ No active BTC 15M markets right now")

        # Show upcoming markets
        print("\nUpcoming markets:")
        markets = kalshi.get_btc_15m_markets()  # Get all
        for m in markets[:5]:
            status = m.get('status', 'unknown')
            close_time = m.get('close_time', '')[:16] if m.get('close_time') else 'N/A'
            print(f"  [{status}] {m.get('ticker')}: closes {close_time}")


def main():
    parser = argparse.ArgumentParser(description="Kalshi BTC 15-Minute Trading Bot")
    parser.add_argument("--live", action="store_true", help="Enable live trading (default: dry run)")
    parser.add_argument("--run", action="store_true", help="Run continuously (default: single pass)")
    parser.add_argument("--duration", type=int, help="Run duration in minutes (with --run)")
    parser.add_argument("--interval", type=int, default=30, help="Check interval in seconds (default: 30)")
    parser.add_argument("--monitor", action="store_true", help="Monitor mode - just show market status")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    # Strategy parameters
    parser.add_argument("--confidence", type=float, default=0.65, help="Min confidence to bet (0-1, default: 0.65)")
    parser.add_argument("--window", type=int, default=10, help="Start betting N minutes before close (default: 10)")
    parser.add_argument("--min-window", type=int, default=2, help="Stop betting N minutes before close (default: 2)")
    parser.add_argument("--min-change", type=float, default=0.05, help="Min %% price change (default: 0.05)")
    parser.add_argument("--max-price", type=int, default=95, help="Max price to pay in cents (default: 95)")
    parser.add_argument("--contracts", type=int, default=10, help="Max contracts per bet (default: 10)")
    parser.add_argument("--min-contracts", type=int, default=2, help="Min contracts per bet (default: 2)")
    parser.add_argument("--no-scale", action="store_true", help="Disable confidence-based position scaling")

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

    # Monitor mode
    if args.monitor:
        monitor_markets(kalshi)
        kalshi.close()
        return

    # Check balance
    balance = kalshi.get_balance()
    print(f"Account balance: ${balance:.2f}")

    if balance < 10 and args.live:
        print("Warning: Low balance. Consider adding funds before live trading.")

    # Configure strategy
    dry_run = not args.live

    print(f"\nMode: {'LIVE TRADING' if args.live else 'DRY RUN'}")
    print(f"Min confidence: {args.confidence:.0%}")
    print(f"Bet window: {args.window}-{args.min_window} minutes before close")
    print(f"Min price change: {args.min_change}%")
    print(f"Max price: {args.max_price}¢")
    if args.no_scale:
        print(f"Contracts per bet: {args.contracts}")
    else:
        print(f"Contracts: {args.min_contracts}-{args.contracts} (scaled by confidence)")
    print()

    # Create and run strategy
    bot = BTCBotStrategy(
        kalshi=kalshi,
        min_confidence=args.confidence,
        max_minutes_before_close=args.window,
        min_minutes_before_close=args.min_window,
        min_price_change_pct=args.min_change,
        max_price=args.max_price,
        contracts_per_bet=args.contracts,
        min_contracts=args.min_contracts,
        scale_by_confidence=not args.no_scale,
        dry_run=dry_run,
        check_interval=args.interval,
        max_daily_risk=100.0,
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
