from defs import BUY, SELL
from indicators import sma
from strategies.base import Decision, Strategy


class MACrossStrategy(Strategy):
    """BUY when the short SMA of the mid close crosses above the long SMA, SELL when it crosses below."""
    name = "ma_cross"

    def __init__(self, params=None):
        super().__init__(params)
        self.short_ma = int(self.params.get("short_ma", 8))
        self.long_ma = int(self.params.get("long_ma", 21))
        if not 0 < self.short_ma < self.long_ma:
            raise ValueError(f"ma_cross needs 0 < short_ma < long_ma, got {self.short_ma}/{self.long_ma}")

    def required_candles(self):
        return self.long_ma + 1

    def decide(self, candles, position=None):
        if len(candles) < self.required_candles():
            return Decision(reason=f"need {self.required_candles()} candles, have {len(candles)}")

        diff = sma(candles.mid_c, self.short_ma) - sma(candles.mid_c, self.long_ma)
        d_prev, d_now = diff.iloc[-2], diff.iloc[-1]

        if d_prev < 0 and d_now > 0:
            return Decision(BUY, reason=f"MA_{self.short_ma} crossed above MA_{self.long_ma}")
        if d_prev > 0 and d_now < 0:
            return Decision(SELL, reason=f"MA_{self.short_ma} crossed below MA_{self.long_ma}")
        return Decision(reason=f"no cross (MA_{self.short_ma} - MA_{self.long_ma} = {d_now:.6g})")
