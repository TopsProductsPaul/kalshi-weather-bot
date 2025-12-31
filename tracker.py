"""Trade tracking and settlement reconciliation."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from clients import KalshiClient
from errors import KalshiAPIError


TRADES_FILE = Path("trades.json")


@dataclass
class Trade:
    """A recorded trade."""
    ticker: str
    contracts: int
    price: float  # Entry price in cents
    side: str  # "buy" or "sell"
    placed_at: str  # ISO timestamp
    cost: float  # Total cost in dollars

    # Settlement info (filled later)
    settled: bool = False
    settled_at: Optional[str] = None
    result: Optional[str] = None  # "yes" or "no"
    payout: float = 0.0  # Payout in dollars
    pnl: float = 0.0  # Profit/loss in dollars


class TradeTracker:
    """Track trades and check settlements."""

    def __init__(self, trades_file: Path = TRADES_FILE):
        self.trades_file = trades_file
        self.trades: list[Trade] = []
        self._load()

    def _load(self):
        """Load trades from file."""
        if self.trades_file.exists():
            with open(self.trades_file, "r") as f:
                data = json.load(f)
                self.trades = [Trade(**t) for t in data]

    def _save(self):
        """Save trades to file."""
        with open(self.trades_file, "w") as f:
            json.dump([asdict(t) for t in self.trades], f, indent=2)

    def record_trade(
        self,
        ticker: str,
        contracts: int,
        price: float,
        side: str = "buy",
    ) -> Trade:
        """Record a new trade."""
        cost = (contracts * price) / 100

        trade = Trade(
            ticker=ticker,
            contracts=contracts,
            price=price,
            side=side,
            placed_at=datetime.now().isoformat(),
            cost=cost,
        )

        self.trades.append(trade)
        self._save()

        return trade

    def get_unsettled(self) -> list[Trade]:
        """Get trades that haven't been settled yet."""
        return [t for t in self.trades if not t.settled]

    def check_settlements(self, kalshi: KalshiClient) -> list[Trade]:
        """
        Check Kalshi for settled markets and update trades.

        Returns list of newly settled trades.
        """
        unsettled = self.get_unsettled()
        newly_settled = []

        for trade in unsettled:
            try:
                market = kalshi.get_market(trade.ticker)
                status = market.get("status", "")
                result = market.get("result", "")

                if status in ("settled", "finalized") and result:
                    # Market has settled
                    trade.settled = True
                    trade.settled_at = datetime.now().isoformat()
                    trade.result = result.lower()

                    # Calculate payout
                    if trade.side == "buy":
                        if trade.result == "yes":
                            # Won: get $1 per contract
                            trade.payout = trade.contracts * 1.0
                        else:
                            # Lost: get nothing
                            trade.payout = 0.0
                    else:
                        # Sold YES (bought NO)
                        if trade.result == "no":
                            trade.payout = trade.contracts * 1.0
                        else:
                            trade.payout = 0.0

                    # Calculate P&L
                    trade.pnl = trade.payout - trade.cost

                    newly_settled.append(trade)

            except KalshiAPIError as e:
                # Market might not exist anymore
                print(f"Warning: Could not check {trade.ticker}: {e}")

        if newly_settled:
            self._save()

        return newly_settled

    def get_summary(self) -> dict:
        """Get summary statistics."""
        settled = [t for t in self.trades if t.settled]
        unsettled = [t for t in self.trades if not t.settled]

        wins = [t for t in settled if t.pnl > 0]
        losses = [t for t in settled if t.pnl < 0]

        total_pnl = sum(t.pnl for t in settled)
        total_cost = sum(t.cost for t in settled)

        return {
            "total_trades": len(self.trades),
            "settled": len(settled),
            "unsettled": len(unsettled),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(settled) if settled else 0,
            "total_pnl": total_pnl,
            "total_wagered": total_cost,
            "roi": (total_pnl / total_cost * 100) if total_cost > 0 else 0,
        }

    def print_report(self):
        """Print a formatted report."""
        summary = self.get_summary()

        print("\n" + "=" * 50)
        print("TRADE TRACKER REPORT")
        print("=" * 50)

        print(f"\nTotal trades: {summary['total_trades']}")
        print(f"Settled: {summary['settled']}")
        print(f"Unsettled: {summary['unsettled']}")

        if summary['settled'] > 0:
            print(f"\nWins: {summary['wins']}")
            print(f"Losses: {summary['losses']}")
            print(f"Win rate: {summary['win_rate']*100:.1f}%")
            print(f"\nTotal wagered: ${summary['total_wagered']:.2f}")
            print(f"Total P&L: ${summary['total_pnl']:+.2f}")
            print(f"ROI: {summary['roi']:+.1f}%")

        # Show recent trades
        print("\n" + "-" * 50)
        print("RECENT TRADES")
        print("-" * 50)

        for trade in self.trades[-10:]:  # Last 10
            status = "✓" if trade.settled else "⏳"
            pnl_str = f"${trade.pnl:+.2f}" if trade.settled else "pending"
            result_str = trade.result.upper() if trade.result else ""

            print(f"{status} {trade.ticker}")
            print(f"   {trade.contracts}x @ {trade.price}¢ = ${trade.cost:.2f}")
            print(f"   {result_str} → {pnl_str}")
            print()


def check_and_report(kalshi: KalshiClient):
    """Check settlements and print report."""
    tracker = TradeTracker()

    print("Checking settlements...")
    newly_settled = tracker.check_settlements(kalshi)

    if newly_settled:
        print(f"\n{len(newly_settled)} trades just settled:")
        for trade in newly_settled:
            emoji = "🎉" if trade.pnl > 0 else "❌"
            print(f"  {emoji} {trade.ticker}: ${trade.pnl:+.2f}")

    tracker.print_report()
