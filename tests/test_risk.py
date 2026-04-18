"""Tests for risk sizing functions."""

import pytest

from src.risk.sizing import (
    calculate_position_size,
    calculate_sl_tp_pct,
    calculate_sl_tp_prices,
)


class TestSlTpPrices:
    def test_sl_below_entry(self):
        sl, tp = calculate_sl_tp_prices(100.0, 2.0, 1.5, 2.0)
        assert sl < 100.0

    def test_tp_above_entry(self):
        sl, tp = calculate_sl_tp_prices(100.0, 2.0, 1.5, 2.0)
        assert tp > 100.0

    def test_exact_values(self):
        # entry=100, atr=2, sl_mult=1.5, tp_mult=2.0
        sl, tp = calculate_sl_tp_prices(100.0, 2.0, 1.5, 2.0)
        assert sl == pytest.approx(97.0)
        assert tp == pytest.approx(104.0)

    def test_larger_multiplier_wider_range(self):
        sl1, tp1 = calculate_sl_tp_prices(100.0, 2.0, 1.0, 1.0)
        sl2, tp2 = calculate_sl_tp_prices(100.0, 2.0, 2.0, 2.0)
        assert sl2 < sl1
        assert tp2 > tp1


class TestSlTpPct:
    def test_sl_pct_positive(self):
        sl_pct, tp_pct = calculate_sl_tp_pct(100.0, 97.0, 104.0)
        assert sl_pct > 0

    def test_tp_pct_positive(self):
        sl_pct, tp_pct = calculate_sl_tp_pct(100.0, 97.0, 104.0)
        assert tp_pct > 0

    def test_exact_percentages(self):
        # entry=100, sl=97 → 3%, tp=104 → 4%
        sl_pct, tp_pct = calculate_sl_tp_pct(100.0, 97.0, 104.0)
        assert sl_pct == pytest.approx(0.03)
        assert tp_pct == pytest.approx(0.04)

    def test_zero_entry_raises(self):
        with pytest.raises(ValueError):
            calculate_sl_tp_pct(0.0, -3.0, 4.0)


class TestPositionSize:
    def test_basic_calculation(self):
        # balance=10_000, risk=1%, entry=100, sl=98 → risk_amount=100, distance=2 → size=50
        size = calculate_position_size(10_000.0, 1.0, 100.0, 98.0)
        assert size == pytest.approx(50.0)

    def test_larger_balance_larger_size(self):
        s1 = calculate_position_size(10_000.0, 1.0, 100.0, 98.0)
        s2 = calculate_position_size(20_000.0, 1.0, 100.0, 98.0)
        assert s2 == pytest.approx(s1 * 2)

    def test_higher_risk_pct_larger_size(self):
        s1 = calculate_position_size(10_000.0, 1.0, 100.0, 98.0)
        s2 = calculate_position_size(10_000.0, 2.0, 100.0, 98.0)
        assert s2 == pytest.approx(s1 * 2)

    def test_wider_sl_smaller_size(self):
        s1 = calculate_position_size(10_000.0, 1.0, 100.0, 98.0)   # sl_dist=2
        s2 = calculate_position_size(10_000.0, 1.0, 100.0, 96.0)   # sl_dist=4
        assert s2 == pytest.approx(s1 / 2)

    def test_sl_at_entry_returns_zero(self):
        size = calculate_position_size(10_000.0, 1.0, 100.0, 100.0)
        assert size == 0.0

    def test_sl_above_entry_returns_zero(self):
        size = calculate_position_size(10_000.0, 1.0, 100.0, 105.0)
        assert size == 0.0
