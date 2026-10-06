import math

import pandas as pd
import pytest

from defs import BUY, NONE, SELL
from helpers import cross_down_candles, cross_up_candles, flat_candles
from indicators import atr
from strategies import build_strategy
from strategies.ma_cross import MACrossStrategy


def test_ma_cross_buy_on_upward_cross():
    decision = MACrossStrategy({"short_ma": 8, "long_ma": 21}).decide(cross_up_candles())
    assert decision.signal == BUY
    assert "crossed above" in decision.reason


def test_ma_cross_sell_on_downward_cross():
    assert MACrossStrategy({"short_ma": 8, "long_ma": 21}).decide(cross_down_candles()).signal == SELL


def test_ma_cross_no_signal_before_the_cross():
    candles = cross_up_candles().iloc[:-1]
    assert MACrossStrategy({"short_ma": 8, "long_ma": 21}).decide(candles).signal == NONE


def test_ma_cross_needs_enough_candles():
    decision = MACrossStrategy({"short_ma": 8, "long_ma": 21}).decide(cross_up_candles().tail(10))
    assert decision.signal == NONE
    assert "need 22 candles" in decision.reason


def test_ma_cross_rejects_bad_params():
    with pytest.raises(ValueError):
        MACrossStrategy({"short_ma": 21, "long_ma": 8})


def test_build_strategy_by_name():
    assert isinstance(build_strategy("ma_cross", {"short_ma": 2, "long_ma": 5}), MACrossStrategy)


def test_atr_of_constant_range():
    values = atr(flat_candles(n=20, candle_range=0.001), period=14)
    assert math.isnan(values.iloc[12])
    assert values.iloc[-1] == pytest.approx(0.001)


def test_atr_uses_gap_from_previous_close():
    df = pd.DataFrame({"mid_o": [10, 12.5], "mid_h": [10.5, 13], "mid_l": [9.5, 12], "mid_c": [10, 12.5]})
    # second candle: high - previous close = 3 is larger than its own range of 1
    assert atr(df, period=1).iloc[-1] == pytest.approx(3)
