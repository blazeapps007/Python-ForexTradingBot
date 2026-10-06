import pandas as pd

from brokers.base import InstrumentInfo, Position
from config import AppConfig
from defs import BUY, NONE, SELL
from helpers import FakeBroker, StubStrategy, flat_candles, make_inst
from strategies.base import Decision
from trade_manager import TradeManager
from bot import TradingBot


def process(broker, decision, inst=None):
    return TradeManager().process(inst or make_inst(), broker, StubStrategy(decision),
                                  flat_candles(), lambda: len(broker.positions))


def test_opens_with_stop_loss_and_take_profit():
    broker = FakeBroker()
    assert process(broker, Decision(BUY)) == "opened"
    order = broker.opened[0]
    assert order.stop_loss < order.entry_estimate < order.take_profit
    assert order.size > 0


def test_no_signal_does_nothing():
    broker = FakeBroker()
    assert process(broker, Decision(NONE)) == "no_signal"
    assert broker.opened == []


def test_same_direction_signal_holds():
    broker = FakeBroker()
    broker.positions["EUR_USD"] = Position("EUR_USD", BUY, 1000)
    assert process(broker, Decision(BUY)) == "hold"
    assert broker.opened == [] and broker.closed == []


def test_opposite_signal_reverses_when_shorting_allowed():
    broker = FakeBroker()
    broker.positions["EUR_USD"] = Position("EUR_USD", SELL, 1000)
    assert process(broker, Decision(BUY)) == "opened"
    assert broker.closed == ["EUR_USD"]
    assert broker.positions["EUR_USD"].side == BUY


def test_spot_sell_only_exits():
    broker = FakeBroker(can_short=False)
    broker.positions["EUR_USD"] = Position("EUR_USD", BUY, 1000)
    assert process(broker, Decision(SELL)) == "exited"
    assert broker.closed == ["EUR_USD"] and broker.opened == []


def test_spot_sell_without_position_is_skipped():
    broker = FakeBroker(can_short=False)
    assert process(broker, Decision(SELL)) == "skip_short"
    assert broker.opened == []


def test_risk_rejection_places_nothing():
    broker = FakeBroker(instrument=InstrumentInfo("EUR_USD", 0.00001, 1, min_size=10_000_000))
    assert process(broker, Decision(BUY)) == "rejected"
    assert broker.opened == []


def make_bot(broker, decision):
    inst = make_inst()
    bot = TradingBot(AppConfig(instruments=[inst]), {"fake": broker}, sleep=lambda s: None)
    bot.strategies[inst.key] = StubStrategy(decision)
    return bot, inst


def add_candle(broker):
    last = broker.candles.iloc[[-1]].copy()
    last["time"] = last["time"] + pd.Timedelta(minutes=5)
    broker.candles = pd.concat([broker.candles, last], ignore_index=True)


def test_bot_warms_up_then_trades_on_next_candle():
    broker = FakeBroker(candles=flat_candles(n=30))
    bot, inst = make_bot(broker, Decision(BUY))

    assert bot.run_once() == {inst.key: "warmup"}
    assert bot.run_once() == {inst.key: "waiting"}

    add_candle(broker)
    assert bot.run_once() == {inst.key: "opened"}
    assert broker.reconciled == ["EUR_USD"]
    assert broker.opened[0].stop_loss < broker.opened[0].entry_estimate


def test_bot_survives_broker_errors():
    broker = FakeBroker(candles=flat_candles(n=30))
    bot, inst = make_bot(broker, Decision(BUY))
    bot.run_once()
    add_candle(broker)

    def boom(symbol, granularity):
        raise RuntimeError("network down")
    broker.reconcile = boom
    assert bot.run_once() == {inst.key: "error"}
