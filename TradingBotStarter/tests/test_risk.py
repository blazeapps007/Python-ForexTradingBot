import pytest

from brokers.base import InstrumentInfo, Quote
from defs import BUY, NONE, SELL
from helpers import flat_candles
from risk import RiskError, RiskSettings, build_order
from strategies.base import Decision

EURUSD = InstrumentInfo("EUR_USD", tick_size=0.00001, step_size=1, min_size=1, quote_currency="USD")
QUOTE = Quote(bid=1.0999, ask=1.1001)


def order_for(decision, quote=QUOTE, instrument=EURUSD, balance=10000.0, open_positions=0,
              settings=None, max_size=None):
    return build_order(decision, symbol=instrument.symbol, candles=flat_candles(candle_range=0.001),
                       quote=quote, instrument=instrument, balance=balance, open_positions=open_positions,
                       settings=settings or RiskSettings(), max_size=max_size)


def test_buy_sl_tp_from_atr_and_risk_sized():
    order = order_for(Decision(BUY, reason="test"))
    # ATR 0.001 x 1.5 = 0.0015 below the ask; TP twice that distance above
    assert order.entry_estimate == 1.1001
    assert order.stop_loss == pytest.approx(1.0986)
    assert order.take_profit == pytest.approx(1.1031)
    # 1% of 10,000 = 100 risk / 0.0015 per unit
    assert order.size == 66666
    assert order.risk_amount == pytest.approx(100, abs=0.01)
    assert order.reason == "test"


def test_sell_uses_bid_and_mirrors_levels():
    order = order_for(Decision(SELL))
    assert order.entry_estimate == 1.0999
    assert order.stop_loss == pytest.approx(1.1014)
    assert order.take_profit == pytest.approx(1.0969)
    assert order.stop_loss > order.entry_estimate > order.take_profit


def test_quote_conversion_changes_size():
    # a loss of 1 quote unit is worth 0.5 account units, so twice the size gives the same risk
    order = order_for(Decision(BUY), quote=Quote(bid=1.0999, ask=1.1001, quote_to_account=0.5))
    assert order.size == 133333


def test_strategy_stop_loss_is_kept_and_tp_follows_rr():
    order = order_for(Decision(BUY, stop_loss=1.0991))
    assert order.stop_loss == pytest.approx(1.0991)
    assert order.take_profit == pytest.approx(1.1001 + 2 * 0.0010)


def test_prices_rounded_to_tick():
    instrument = InstrumentInfo("X", tick_size=0.01, step_size=0.001, min_size=0.001)
    order = order_for(Decision(BUY), quote=Quote(bid=100.003, ask=100.004), instrument=instrument,
                      settings=RiskSettings(sl_atr_mult=1.5))
    assert order.stop_loss == pytest.approx(100.0)   # 100.004 - 0.0015 rounds to 100.00
    assert order.size == pytest.approx(round(order.size, 3))


def test_max_size_caps_order():
    assert order_for(Decision(BUY), max_size=500).size == 500


@pytest.mark.parametrize("kwargs, message", [
    ({"settings": RiskSettings(risk_pct=6)}, "risk_pct"),
    ({"open_positions": 5}, "limit is 5"),
    ({"quote": Quote(1.0999, 1.1001, quote_to_account=None)}, "convert"),
    ({"instrument": InstrumentInfo("EUR_USD", 0.00001, 1, min_size=1_000_000)}, "below minimum"),
    ({"instrument": InstrumentInfo("EUR_USD", 0.00001, 1, 1, min_notional=1_000_000)}, "order value"),
])
def test_guardrails_reject(kwargs, message):
    with pytest.raises(RiskError, match=message):
        order_for(Decision(BUY), **kwargs)


def test_rejects_no_signal():
    with pytest.raises(RiskError):
        order_for(Decision(NONE))


def test_rejects_stop_loss_on_wrong_side():
    with pytest.raises(RiskError, match="SL < entry"):
        order_for(Decision(BUY, stop_loss=1.2))


def test_rejects_stop_inside_the_spread():
    # ATR 0.001 x 1.5 = 0.0015 stop distance, but the spread is 0.001
    with pytest.raises(RiskError, match="spread"):
        order_for(Decision(BUY), quote=Quote(bid=1.0995, ask=1.1005))
    assert order_for(Decision(BUY), quote=Quote(bid=1.0995, ask=1.1005),
                     settings=RiskSettings(min_sl_spreads=1.0)).size > 0


def test_rejects_when_atr_unavailable():
    with pytest.raises(RiskError, match="ATR"):
        build_order(Decision(BUY), symbol="EUR_USD", candles=flat_candles(n=5), quote=QUOTE,
                    instrument=EURUSD, balance=10000, open_positions=0, settings=RiskSettings())
