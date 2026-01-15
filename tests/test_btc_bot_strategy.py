"""Unit tests for BTCBotStrategy internal logic.

Covers:
1) _calculate_confidence with momentum and large moves
2) _detect_momentum direction confirmation
3) _scale_contracts linear scaling
4) _execute_best_up_trade order selection with max price constraints
5) _execute_best_down_trade order selection with max price constraints
"""

import pytest

from strategy.btc_bot import BTCBotStrategy


def make_strategy(**kwargs) -> BTCBotStrategy:
    """Create a BTCBotStrategy with minimal dependencies for unit tests."""
    # We pass kalshi=None since we'll stub out place_order where needed.
    return BTCBotStrategy(kalshi=None, dry_run=True, **kwargs)


class TestCalculateConfidence:
    def test_calculates_with_momentum_and_large_move(self):
        s = make_strategy()
        # 0.20% move, 2 minutes left, momentum=True
        conf = s._calculate_confidence(price_change_pct=0.20, minutes_left=2, has_momentum=True)
        # Expected around 0.79 given formula; allow small tolerance
        assert conf == pytest.approx(0.791, abs=0.02)


class TestDetectMomentum:
    def test_detects_momentum_in_expected_direction(self):
        s = make_strategy()

        # Upward momentum: 3 consecutive positive changes
        s._price_history = [100.0, 100.5, 101.0, 101.2]
        assert s._detect_momentum(is_up=True) is True

        # Downward momentum: 3 consecutive negative changes
        s._price_history = [100.0, 99.7, 99.3, 99.1]
        assert s._detect_momentum(is_up=False) is True

        # Not enough history
        s._price_history = [100.0, 100.2]
        assert s._detect_momentum(is_up=True) is False


class TestScaleContracts:
    def test_scales_linearly_between_min_and_max(self):
        s = make_strategy(min_confidence=0.65, contracts_per_bet=10, min_contracts=2, scale_by_confidence=True)

        # At minimum confidence → min_contracts
        assert s._scale_contracts(0.65) == 2

        # At full confidence → max contracts
        assert s._scale_contracts(1.0) == 10

        # Mid confidence (0.80) → linear interpolation
        # conf_pct = (0.80-0.65)/0.35 ≈ 0.4286 → 2 + 0.4286*(8) ≈ 5.43 → int() = 5
        assert s._scale_contracts(0.80) == 5


class TestExecuteBestTrades:
    def test_execute_best_up_trade_uses_sell_no_when_yes_too_expensive(self, monkeypatch):
        s = make_strategy(max_price=95)

        calls = {}

        def fake_place_order(ticker: str, contracts: int, price: int, side: str):
            calls["args"] = {
                "ticker": ticker,
                "contracts": contracts,
                "price": price,
                "side": side,
            }
            return object()  # truthy sentinel

        # Stub out place_order so we don't hit Strategy.place_order (and no file writes)
        monkeypatch.setattr(s, "place_order", fake_place_order)

        # yes_ask > max_price → fallback to SELL NO (implemented as BUY YES @ 100 - no_bid)
        executed = s._execute_best_up_trade(
            ticker="KXBTC15M-TEST",
            yes_ask=98,
            no_bid=20,
            contracts=7,
            confidence=0.8,
        )

        assert executed is True
        assert calls["args"]["ticker"] == "KXBTC15M-TEST"
        assert calls["args"]["contracts"] == 7
        # SELL NO path buys YES at 100 - no_bid = 80
        assert calls["args"]["price"] == 80
        assert calls["args"]["side"] == "buy"

    def test_execute_best_down_trade_uses_sell_yes_when_no_too_expensive(self, monkeypatch):
        s = make_strategy(max_price=95)

        calls = {}

        def fake_place_order(ticker: str, contracts: int, price: int, side: str):
            calls["args"] = {
                "ticker": ticker,
                "contracts": contracts,
                "price": price,
                "side": side,
            }
            return object()  # truthy sentinel

        monkeypatch.setattr(s, "place_order", fake_place_order)

        # no_ask > max_price and YES bid exists with acceptable risk → SELL YES @ yes_bid
        executed = s._execute_best_down_trade(
            ticker="KXBTC15M-TEST",
            yes_bid=12,
            no_ask=98,
            contracts=6,
            confidence=0.8,
        )

        assert executed is True
        assert calls["args"]["ticker"] == "KXBTC15M-TEST"
        assert calls["args"]["contracts"] == 6
        assert calls["args"]["price"] == 12
        assert calls["args"]["side"] == "sell"
