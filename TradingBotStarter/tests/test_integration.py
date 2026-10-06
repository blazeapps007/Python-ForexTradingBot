"""Network tests against broker test environments. Run with:

    docker compose run --rm tests pytest -m integration

Tests that place orders run only when keys are present in .env, and never against live accounts.
"""
import math
import os
import time

import ccxt
import pytest

from brokers.base import Order
from brokers.binance_futures import BinanceFuturesBroker
from brokers.binance_spot import BinanceSpotBroker
from brokers.ccxt_common import make_exchange
from brokers.oanda import OandaBroker
from defs import BUY, SELL
from precision import round_to_step

pytestmark = pytest.mark.integration

OANDA_READY = os.environ.get("OANDA_API_KEY") and os.environ.get("OANDA_ACCOUNT_ID") \
    and os.environ.get("OANDA_ENV", "practice") == "practice"
BINANCE_TEST_ENV = os.environ.get("BINANCE_ENV", "testnet") in ("testnet", "demo")
BINANCE_READY = os.environ.get("BINANCE_API_KEY") and os.environ.get("BINANCE_API_SECRET") and BINANCE_TEST_ENV
FUTURES_KEY = os.environ.get("BINANCE_FUTURES_API_KEY") or os.environ.get("BINANCE_API_KEY")
FUTURES_SECRET = os.environ.get("BINANCE_FUTURES_API_SECRET") or os.environ.get("BINANCE_API_SECRET")
FUTURES_READY = FUTURES_KEY and FUTURES_SECRET and BINANCE_TEST_ENV


def small_order(broker, symbol, side, sl_pct=0.01, rr=2.0):
    """Smallest allowed order with SL/TP a percentage away from the current price."""
    quote = broker.get_quote(symbol)
    info = broker.get_instrument(symbol)
    entry = quote.ask if side == BUY else quote.bid
    size = max(info.min_size, info.min_notional * 1.5 / entry)
    size = math.ceil(size / info.step_size) * info.step_size
    distance = entry * sl_pct
    sl, tp = (entry - distance, entry + distance * rr) if side == BUY else (entry + distance, entry - distance * rr)
    return Order(symbol, side, size, entry, round_to_step(sl, info.tick_size), round_to_step(tp, info.tick_size))


# ---------- no keys needed ----------

def test_live_spot_prices_from_public_mirror():
    broker = BinanceSpotBroker(make_exchange(ccxt.binance, None, None, "data", ["spot"]))
    candles = broker.get_candles("BTC/USDT", "M5", 10)
    assert len(candles) == 10
    assert candles.time.iloc[-1].timestamp() + 300 <= time.time()      # only complete candles
    quote = broker.get_quote("TSLAB/USDT")
    assert 0 < quote.bid < quote.ask
    info = broker.get_instrument("TSLAB/USDT")
    assert info.tick_size == 0.01 and info.min_notional == 5.0


def test_futures_sl_tp_become_reduce_only_algo_orders():
    exchange = make_exchange(ccxt.binanceusdm, None, None, "testnet", ["linear"])
    exchange.load_markets()
    for params, order_type in (({"stopLossPrice": 1000}, "STOP_MARKET"), ({"takeProfitPrice": 9000}, "TAKE_PROFIT_MARKET")):
        request = exchange.create_order_request("ETH/USDT:USDT", "market", "sell", 0.01, None,
                                                {**params, "reduceOnly": True, "isAlgoOrder": True})
        assert request["type"] == order_type
        assert str(request["reduceOnly"]).lower() == "true"
        assert "triggerPrice" in request


# ---------- order round trips (need test keys) ----------

@pytest.mark.skipif(not OANDA_READY, reason="needs OANDA practice keys in .env")
def test_oanda_practice_round_trip():
    broker = OandaBroker(os.environ["OANDA_API_KEY"], os.environ["OANDA_ACCOUNT_ID"], "practice")
    order = small_order(broker, "EUR_USD", BUY)
    result = broker.open_position(order)
    assert result.ok, result.error
    try:
        p = broker.get_position("EUR_USD")
        assert p.stop_loss is not None and p.take_profit is not None
    finally:
        assert broker.close_position("EUR_USD")


@pytest.mark.skipif(not BINANCE_READY, reason="needs Binance testnet/demo keys in .env")
def test_binance_spot_round_trip(tmp_path):
    exchange = make_exchange(ccxt.binance, os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"],
                             os.environ.get("BINANCE_ENV", "testnet"), ["spot"])
    broker = BinanceSpotBroker(exchange, state_file=str(tmp_path / "state.json"))
    result = broker.open_position(small_order(broker, "BTC/USDT", BUY))
    assert result.ok, result.error
    try:
        open_orders = exchange.fetch_open_orders("BTC/USDT")
        assert sum(str(o["info"].get("orderListId")) == result.position.id for o in open_orders) == 2
    finally:
        assert broker.close_position("BTC/USDT")


@pytest.mark.skipif(not FUTURES_READY, reason="needs Binance futures testnet/demo keys in .env")
def test_binance_futures_round_trip():
    exchange = make_exchange(ccxt.binanceusdm, FUTURES_KEY, FUTURES_SECRET,
                             os.environ.get("BINANCE_ENV", "testnet"), ["linear"])
    broker = BinanceFuturesBroker(exchange, leverage={"ETH/USDT:USDT": 1})
    result = broker.open_position(small_order(broker, "ETH/USDT:USDT", SELL))
    assert result.ok, result.error
    try:
        assert len(exchange.fetch_open_orders("ETH/USDT:USDT", None, None, {"trigger": True})) == 2
    finally:
        assert broker.close_position("ETH/USDT:USDT")
