import pytest
import requests

from brokers.base import BrokerError, Order
from brokers.oanda import OandaBroker
from defs import BUY, SELL
from helpers import FakeResponse, FakeSession

ACC = "/accounts/ACC"
INSTRUMENTS = FakeResponse(200, {"instruments": [
    {"name": "EUR_USD", "displayPrecision": 5, "tradeUnitsPrecision": 0, "minimumTradeSize": "1"},
    {"name": "USD_JPY", "displayPrecision": 3, "tradeUnitsPrecision": 0, "minimumTradeSize": "1"},
]})


def broker(routes):
    session = FakeSession({("GET", ACC + "/instruments"): INSTRUMENTS, **routes})
    return OandaBroker("KEY", "ACC", "practice", session=session), session


def fill(units, trade_id="261", price="1.10012"):
    return FakeResponse(201, {"orderFillTransaction": {"price": price, "tradeOpened": {"tradeID": trade_id, "units": units}}})


def test_market_order_carries_stop_loss_and_take_profit():
    b, session = broker({("POST", ACC + "/orders"): fill("-1000")})
    result = b.open_position(Order("EUR_USD", SELL, 1000, 1.1, stop_loss=1.101504, take_profit=1.096996))

    body = session.calls[-1]["body"]["order"]
    assert body["type"] == "MARKET" and body["units"] == "-1000"
    assert body["stopLossOnFill"] == {"price": "1.10150", "timeInForce": "GTC"}
    assert body["takeProfitOnFill"] == {"price": "1.09700", "timeInForce": "GTC"}
    assert result.ok and result.position.id == "261" and result.position.entry_price == 1.10012


def test_price_precision_follows_instrument():
    b, session = broker({("POST", ACC + "/orders"): fill("500")})
    b.open_position(Order("USD_JPY", BUY, 500, 150.0, stop_loss=149.12345, take_profit=151.98765))
    body = session.calls[-1]["body"]["order"]
    assert body["stopLossOnFill"]["price"] == "149.123"
    assert body["takeProfitOnFill"]["price"] == "151.988"


def test_cancelled_order_is_reported():
    cancelled = FakeResponse(201, {"orderCancelTransaction": {"reason": "STOP_LOSS_ON_FILL_LOSS"}})
    b, _ = broker({("POST", ACC + "/orders"): cancelled})
    result = b.open_position(Order("EUR_USD", BUY, 1000, 1.1, 1.09, 1.12))
    assert not result.ok and result.error == "STOP_LOSS_ON_FILL_LOSS"


def test_network_error_does_not_raise():
    b, _ = broker({("POST", ACC + "/orders"): requests.ConnectionError("down")})
    result = b.open_position(Order("EUR_USD", BUY, 1000, 1.1, 1.09, 1.12))
    assert not result.ok and "down" in result.error


def test_headers_are_not_mutated():
    b, session = broker({("POST", ACC + "/orders"): fill("1000")})
    original = dict(b.headers)
    b.open_position(Order("EUR_USD", BUY, 1000, 1.1, 1.09, 1.12))
    session.calls[-1]["headers"]["X-Test"] = "changed"
    assert b.headers == original


def test_candles_request_honours_count_and_drops_incomplete():
    candle = {"complete": True, "volume": 10, "mid": {"o": "1", "h": "2", "l": "0.5", "c": "1.5"}}
    candles = [dict(candle, time=f"2026-01-01T00:0{i}:00.000000000Z") for i in range(5)]
    candles.append(dict(candle, time="2026-01-01T00:05:00.000000000Z", complete=False))
    b, session = broker({("GET", "/instruments/EUR_USD/candles"): FakeResponse(200, {"candles": candles})})

    df = b.get_candles("EUR_USD", "M1", 3)
    assert session.calls[-1]["params"]["count"] == 4
    assert len(df) == 3 and str(df.time.iloc[-1]) == "2026-01-01 00:04:00+00:00"
    assert df.mid_c.iloc[-1] == 1.5


def test_quote_uses_home_conversion_for_losses():
    pricing = FakeResponse(200, {
        "prices": [{"bids": [{"price": "0.85010"}], "asks": [{"price": "0.85020"}]}],
        "homeConversions": [{"currency": "GBP", "accountGain": "1.27", "accountLoss": "1.28"}],
    })
    b, _ = broker({("GET", ACC + "/pricing"): pricing})
    quote = b.get_quote("EUR_GBP")
    assert (quote.bid, quote.ask, quote.quote_to_account) == (0.8501, 0.8502, 1.28)


def test_position_from_open_trades():
    trades = FakeResponse(200, {"trades": [
        {"id": "7", "instrument": "EUR_USD", "currentUnits": "-1000", "price": "1.1",
         "stopLossOrder": {"price": "1.102"}, "takeProfitOrder": {"price": "1.096"}},
        {"id": "8", "instrument": "GBP_USD", "currentUnits": "500", "price": "1.3"},
    ]})
    b, _ = broker({("GET", ACC + "/openTrades"): trades})
    p = b.get_position("EUR_USD")
    assert (p.side, p.size, p.stop_loss, p.take_profit, p.id) == (SELL, 1000, 1.102, 1.096, "7")
    assert b.get_position("USD_JPY") is None


def test_position_lookup_failure_raises():
    b, _ = broker({("GET", ACC + "/openTrades"): FakeResponse(503, {"errorMessage": "busy"})})
    with pytest.raises(BrokerError, match="busy"):
        b.get_position("EUR_USD")
