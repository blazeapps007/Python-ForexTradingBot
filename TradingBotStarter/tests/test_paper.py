import pandas as pd
import pytest

from brokers.base import Order, Quote
from brokers.paper import PaperAccount, PaperBroker, exit_hit
from defs import BUY, SELL
from helpers import FakeBroker, flat_candles


def candle(o, h, l, c):
    return pd.Series({"mid_o": o, "mid_h": h, "mid_l": l, "mid_c": c})


@pytest.mark.parametrize("side, bar, expected", [
    (BUY, candle(100, 105, 99, 104), ("take_profit", 104)),
    (BUY, candle(100, 101, 97, 98), ("stop_loss", 98)),
    (BUY, candle(100, 105, 97, 100), ("stop_loss", 98)),        # both hit: assume stop loss first
    (BUY, candle(95, 96, 94, 95), ("stop_loss", 95)),           # gap below the stop fills at the open
    (BUY, candle(100, 101, 99, 100), (None, None)),
    (SELL, candle(100, 101, 95, 96), ("take_profit", 96)),
    (SELL, candle(100, 103, 99, 102), ("stop_loss", 102)),
])
def test_exit_hit(side, bar, expected):
    sl, tp = (98, 104) if side == BUY else (102, 96)
    assert exit_hit(side, bar, sl, tp) == expected


def test_long_uses_bid_prices_when_available():
    bar = pd.Series({"mid_o": 100, "mid_h": 104.05, "mid_l": 99, "mid_c": 104,
                     "bid_o": 99.9, "bid_h": 103.95, "bid_l": 98.9, "bid_c": 103.9})
    assert exit_hit(BUY, bar, 98, 104) == (None, None)


def paper(tmp_path, data=None, **kwargs):
    account = PaperAccount(10000, state_file=str(tmp_path / "paper.json"), trades_file=str(tmp_path / "trades.csv"))
    data = data or FakeBroker(quote=Quote(bid=99.9, ask=100.1))
    return PaperBroker("binance_spot", data, account, **kwargs), account, data


def test_paper_fill_and_take_profit(tmp_path):
    broker, account, data = paper(tmp_path)
    result = broker.open_position(Order("BTC/USDT", BUY, 2, 100.0, stop_loss=98.0, take_profit=104.0))
    assert result.ok and result.position.entry_price == 100.1      # bought at the ask
    assert result.position.take_profit == pytest.approx(104.1)

    account.positions["binance_spot:BTC/USDT"]["opened_at"] = "2026-01-01T00:00:00+00:00"
    data.candles = flat_candles(n=3, price=100, candle_range=1.0)
    data.candles.loc[2, "mid_h"] = 105.0
    broker.reconcile("BTC/USDT", "M5")

    assert broker.get_position("BTC/USDT") is None
    assert account.balance == pytest.approx(10000 + (104.1 - 100.1) * 2)
    assert "take_profit" in (tmp_path / "trades.csv").read_text()


def test_paper_state_is_saved(tmp_path):
    broker, account, data = paper(tmp_path)
    broker.open_position(Order("BTC/USDT", BUY, 2, 100.0, 98.0, 104.0))
    reloaded = PaperAccount(1, state_file=str(tmp_path / "paper.json"))
    assert reloaded.balance == 10000 and "binance_spot:BTC/USDT" in reloaded.positions


def test_paper_close_on_signal_uses_bid_for_longs(tmp_path):
    broker, account, _ = paper(tmp_path)
    broker.open_position(Order("BTC/USDT", BUY, 1, 100.0, 98.0, 104.0))
    assert broker.close_position("BTC/USDT")
    assert account.balance == pytest.approx(10000 + (99.9 - 100.1))


def test_paper_size_limits(tmp_path):
    spot_broker, _, _ = paper(tmp_path, data=FakeBroker(can_short=False))
    assert spot_broker.max_size("BTC/USDT", BUY, 100.0) == 100        # cash only
    futures_broker, _, _ = paper(tmp_path, can_short=True, leverage={"ETH/USDT:USDT": 3})
    assert futures_broker.max_size("ETH/USDT:USDT", SELL, 100.0) == 300
    assert futures_broker.can_short


def test_paper_symbol_map_for_futures(tmp_path):
    data = FakeBroker()
    seen = []
    data.get_quote = lambda symbol: seen.append(symbol) or Quote(1, 2)
    broker, _, _ = paper(tmp_path, data=data, symbol_map=lambda s: s.split(":")[0])
    broker.get_quote("ETH/USDT:USDT")
    assert seen == ["ETH/USDT"]
