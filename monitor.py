#!/usr/bin/env python3
"""
Overnight monitor - checks orders and logs status every 30 minutes.
Run with: nohup python monitor.py > monitor.log 2>&1 &
"""

import time
from datetime import datetime

from config import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH, KALSHI_ENV
from clients import KalshiClient


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def check_status(kalshi: KalshiClient):
    """Check and log current status."""
    log("=" * 50)
    
    # Balance
    balance = kalshi.get_balance()
    log(f"Balance: ${balance:.2f}")
    
    # Open orders
    orders = kalshi.get_open_orders()
    log(f"Open orders: {len(orders)}")
    for o in orders:
        log(f"  {o.ticker}: {o.size}x @ {o.price}¢ (filled: {o.filled})")
    
    # Positions
    positions = kalshi.get_positions()
    log(f"Positions: {len(positions)}")
    for p in positions:
        log(f"  {p.ticker}: {p.contracts} @ {p.avg_price:.0f}¢")
    
    log("=" * 50)


def main():
    log("Starting overnight monitor...")
    log(f"Connecting to Kalshi ({KALSHI_ENV})...")
    
    kalshi = KalshiClient(
        key_id=KALSHI_API_KEY_ID,
        private_key_path=KALSHI_PRIVATE_KEY_PATH,
        env=KALSHI_ENV,
    )
    
    check_interval = 30 * 60  # 30 minutes
    
    try:
        while True:
            try:
                check_status(kalshi)
            except Exception as e:
                log(f"Error checking status: {e}")
            
            log(f"Next check in {check_interval // 60} minutes...")
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        log("Monitor stopped by user")
    finally:
        kalshi.close()
        log("Monitor ended")


if __name__ == "__main__":
    main()
