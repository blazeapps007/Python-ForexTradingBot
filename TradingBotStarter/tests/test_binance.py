import ccxt
import pytest

from brokers.base import Order
from brokers.binance_futures import BinanceFuturesBroker
from brokers.binance_spot import BinanceSpotBroker
from brokers.ccxt_common import SPOT_DATA_MIRROR, make_exchange, ohlcv_to_df
from defs import BUY, SELL
from helpers import FakeExchange, futures_market, spot_market


# ---------- spot (crypto and bStocks) ----------

def spot(tmp_path, **kwargs):
    exchange = FakeExchange({"BTC/USDT": spot_market(), "TSLAB/USDT": spot_market("TSLAB/USDT", step=0.001)}, **kwargs)
    return BinanceSpotBroker(exchange, state_file=str(tmp_path / "spot_state.json")), exchange


def test_spot_buy_then_oco_exit_orders(tmp_path):
    broker, ex = spot(tmp_path, fill_price=100.5, fees=[{"currency": "BTC", "cost": 0.00001}])
    result = broker.open_position(Order("BTC/USDT", BUY, 0.01, 100.0, stop_loss=98.0, take_profit=104.0))

    assert ex.made("create_order")[0][1:5] == ("BTC/USDT", "market", "buy", 0.01)
    oco = ex.made("oco")[0][1]
    # levels keep their distance from the planned entry, re-anchored to the 100.5 fill
    assert oco == {"symbol": "BTCUSDT", "side": "SELL", "quantity": "0.00999",
                   "aboveType": "LIMIT_MAKER", "abovePrice": "104.5",
                   "belowType": "STOP_LOSS", "belowStopPrice": "98.5"}
    assert result.ok and result.position.id == "77"
    assert broker.get_position("BTC/USDT").stop_loss == 98.5


def test_spot_uses_stop_limit_when_stop_market_not_allowed(tmp_path):
    ex = FakeExchange({"TSLAB/USDT": spot_market("TSLAB/USDT", order_types=["LIMIT", "LIMIT_MAKER", "MARKET", "STOP_LOSS_LIMIT"])},
                      fill_price=400.0)
    broker = BinanceSpotBroker(ex, state_file=str(tmp_path / "s.json"))
    broker.open_position(Order("TSLAB/USDT", BUY, 0.05, 400.0, stop_loss=390.0, take_profit=420.0))
    oco = ex.made("oco")[0][1]
    assert oco["belowType"] == "STOP_LOSS_LIMIT"
    assert oco["belowPrice"] == "389.22" and oco["belowTimeInForce"] == "GTC"


def test_spot_sells_back_if_oco_fails(tmp_path):
    broker, ex = spot(tmp_path, fill_price=100.0, oco_error=ccxt.InvalidOrder("bad price"))
    result = broker.open_position(Order("BTC/USDT", BUY, 0.01, 100.0, 98.0, 104.0))
    sides = [c[3] for c in ex.made("create_order")]
    assert sides == ["buy", "sell"]
    assert not result.ok and broker.get_position("BTC/USDT") is None


def test_spot_is_long_only(tmp_path):
    broker, ex = spot(tmp_path)
    assert not broker.open_position(Order("BTC/USDT", SELL, 0.01, 100.0, 102.0, 96.0)).ok
    assert ex.calls == []


def test_spot_ignores_coins_it_did_not_buy(tmp_path):
    broker, _ = spot(tmp_path, balances={"BTC": {"free": 5.0, "total": 5.0}})
    assert broker.get_position("BTC/USDT") is None
    assert broker.close_position("BTC/USDT") is True


def test_spot_close_cancels_oco_and_sells(tmp_path):
    broker, ex = spot(tmp_path, fill_price=100.0, balances={"BTC": {"free": 0.01, "total": 0.01}})
    broker.open_position(Order("BTC/USDT", BUY, 0.01, 100.0, 98.0, 104.0))
    assert broker.close_position("BTC/USDT")
    assert ex.made("cancel_list")[0][1] == {"symbol": "BTCUSDT", "orderListId": 77}
    assert ex.made("create_order")[-1][1:5] == ("BTC/USDT", "market", "sell", 0.01)
    assert broker.get_position("BTC/USDT") is None


def test_spot_reconcile_drops_position_after_exit_fill(tmp_path):
    broker, ex = spot(tmp_path, fill_price=100.0)
    broker.open_position(Order("BTC/USDT", BUY, 0.01, 100.0, 98.0, 104.0))

    ex.open_orders = [{"info": {"orderListId": 77}}]
    broker.reconcile("BTC/USDT", "M5")
    assert broker.get_position("BTC/USDT") is not None

    ex.open_orders = []
    broker.reconcile("BTC/USDT", "M5")
    assert broker.get_position("BTC/USDT") is None


def test_spot_state_survives_restart(tmp_path):
    broker, ex = spot(tmp_path, fill_price=100.0)
    broker.open_position(Order("BTC/USDT", BUY, 0.01, 100.0, 98.0, 104.0))
    again = BinanceSpotBroker(ex, state_file=str(tmp_path / "spot_state.json"))
    assert again.get_position("BTC/USDT").take_profit == 104.0


# ---------- USD-M futures ----------

def futures(**kwargs):
    ex = FakeExchange({"ETH/USDT:USDT": futures_market()}, **kwargs)
    return BinanceFuturesBroker(ex, leverage={"ETH/USDT:USDT": 3}), ex


def test_futures_short_with_reduce_only_sl_tp():
    broker, ex = futures(fill_price=2001.0)
    result = broker.open_position(Order("ETH/USDT:USDT", SELL, 0.05, 2000.0, stop_loss=2030.0, take_profit=1940.0))

    assert ex.calls[:3] == [("set_position_mode", False, "ETH/USDT:USDT"),
                            ("set_margin_mode", "isolated", "ETH/USDT:USDT"),
                            ("set_leverage", 3, "ETH/USDT:USDT")]
    entry, sl, tp = ex.made("create_order")
    assert entry[1:6] == ("ETH/USDT:USDT", "market", "sell", 0.05, {})
    assert sl[3:6] == ("buy", 0.05, {"stopLossPrice": 2031.0, "reduceOnly": True})
    assert tp[3:6] == ("buy", 0.05, {"takeProfitPrice": 1941.0, "reduceOnly": True})
    assert result.ok and result.position.stop_loss == 2031.0


def test_futures_setting_already_in_place_is_fine():
    broker, ex = futures(fill_price=2000.0,
                         setting_errors={"set_margin_mode": ccxt.ExchangeError('{"code":-4046,"msg":"No need to change margin type."}')})
    assert broker.open_position(Order("ETH/USDT:USDT", BUY, 0.05, 2000.0, 1970.0, 2060.0)).ok


def test_futures_other_setting_errors_stop_the_order():
    broker, ex = futures(setting_errors={"set_position_mode": ccxt.ExchangeError("open positions exist")})
    with pytest.raises(ccxt.ExchangeError):
        broker.open_position(Order("ETH/USDT:USDT", BUY, 0.05, 2000.0, 1970.0, 2060.0))
    assert ex.made("create_order") == []


def test_futures_closes_position_if_sl_tp_fail():
    position = {"symbol": "ETH/USDT:USDT", "contracts": 0.05, "side": "long", "entryPrice": 2000.0}
    broker, ex = futures(fill_price=2000.0, positions=[position], conditional_error=ccxt.InvalidOrder("rejected"))
    result = broker.open_position(Order("ETH/USDT:USDT", BUY, 0.05, 2000.0, 1970.0, 2060.0))
    assert not result.ok
    assert ("cancel_all", "ETH/USDT:USDT", {"trigger": True}) in ex.calls
    assert ex.made("create_order")[-1][3:6] == ("sell", 0.05, {"reduceOnly": True})


def test_futures_reconcile_cancels_leftover_exit_order():
    broker, ex = futures(open_orders=[{"id": "1"}])
    broker.reconcile("ETH/USDT:USDT", "M5")
    assert ("cancel_all", "ETH/USDT:USDT", {"trigger": True}) in ex.calls


def test_futures_position_parsing():
    broker, _ = futures(positions=[{"symbol": "ETH/USDT:USDT", "contracts": 0.2, "side": "short", "entryPrice": 1990.0}])
    p = broker.get_position("ETH/USDT:USDT")
    assert (p.side, p.size, p.entry_price) == (SELL, 0.2, 1990.0)


# ---------- ccxt wiring (offline) ----------

def test_real_ccxt_has_the_endpoints_we_use():
    spot_ex = make_exchange(ccxt.binance, None, None, "testnet", ["spot"])
    assert hasattr(spot_ex, "private_post_orderlist_oco") and hasattr(spot_ex, "private_delete_orderlist")
    assert "testnet.binance.vision" in spot_ex.urls["api"]["private"]
    assert make_exchange(ccxt.binance, None, None, "data", ["spot"]).urls["api"]["public"] == SPOT_DATA_MIRROR
    assert "demo-api.binance.com" in make_exchange(ccxt.binance, None, None, "demo", ["spot"]).urls["api"]["private"]
    assert "testnet.binancefuture.com" in make_exchange(ccxt.binanceusdm, None, None, "testnet", ["linear"]).urls["api"]["fapiPrivate"]
    with pytest.raises(ValueError):
        make_exchange(ccxt.binance, None, None, "mainnet", ["spot"])


def test_ohlcv_drops_candle_still_forming():
    minute = 60_000
    rows = [[0, 1, 2, 0.5, 1.5, 10], [minute, 1.5, 2, 1, 1.8, 12], [2 * minute, 1.8, 2, 1.7, 1.9, 3]]
    df = ohlcv_to_df(rows, "M1", now_ms=2 * minute + 30_000)
    assert len(df) == 2 and df.mid_c.tolist() == [1.5, 1.8]
    assert str(df.time.iloc[0]) == "1970-01-01 00:00:00+00:00"
