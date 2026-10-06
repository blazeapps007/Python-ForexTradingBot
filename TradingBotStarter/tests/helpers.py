import json

import pandas as pd

from brokers.base import Broker, InstrumentInfo, OrderResult, Position, Quote
from config import InstrumentConfig
from indicators import sma
from precision import floor_to_step, round_to_step
from risk import RiskSettings
from strategies.base import Decision, Strategy


def make_candles(closes, start="2026-01-01 00:00", freq="5min", wick=0.0005, spread=0.0002):
    """Candles whose open is the previous close, with bid/ask around mid."""
    rows, prev = [], closes[0]
    for close in closes:
        rows.append({"mid_o": prev, "mid_h": max(prev, close) + wick,
                     "mid_l": min(prev, close) - wick, "mid_c": close})
        prev = close
    df = pd.DataFrame(rows)
    df.insert(0, "time", pd.date_range(start, periods=len(rows), freq=freq, tz="UTC"))
    df.insert(1, "volume", 100)
    for c in "ohlc":
        df[f"bid_{c}"] = df[f"mid_{c}"] - spread / 2
        df[f"ask_{c}"] = df[f"mid_{c}"] + spread / 2
    return df


def flat_candles(n=20, price=1.1, candle_range=0.001, start="2026-01-01 00:00"):
    """Candles with constant close and a fixed high-low range, so ATR == candle_range."""
    df = pd.DataFrame({"mid_o": [price] * n, "mid_c": [price] * n,
                       "mid_h": [price + candle_range / 2] * n, "mid_l": [price - candle_range / 2] * n})
    df.insert(0, "time", pd.date_range(start, periods=n, freq="5min", tz="UTC"))
    df.insert(1, "volume", 100)
    return df


def _cross_candles(direction, short=8, long=21):
    down = [1.2 - 0.001 * i for i in range(30)]
    up = [down[-1] + 0.004 * i for i in range(1, 30)]
    closes = down + up if direction == "up" else [2.4 - c for c in down + up]
    df = make_candles(closes)
    diff = sma(df.mid_c, short) - sma(df.mid_c, long)
    for i in range(1, len(df)):
        if (direction == "up" and diff[i - 1] < 0 < diff[i]) or (direction == "down" and diff[i - 1] > 0 > diff[i]):
            return df.iloc[: i + 1].reset_index(drop=True)
    raise AssertionError("no cross generated")


def cross_up_candles():
    return _cross_candles("up")


def cross_down_candles():
    return _cross_candles("down")


def make_inst(symbol="EUR_USD", broker="fake", **risk):
    return InstrumentConfig(broker=broker, symbol=symbol, strategy="ma_cross", params={},
                            granularity="M5", risk=RiskSettings(**risk))


class StubStrategy(Strategy):
    name = "stub"

    def __init__(self, decision):
        super().__init__({})
        self.decision = decision

    def required_candles(self):
        return 2

    def decide(self, candles, position=None):
        return self.decision


class FakeBroker(Broker):
    name = "fake"

    def __init__(self, candles=None, quote=None, instrument=None, balance=10000.0, can_short=True):
        self.candles = candles
        self.quote = quote or Quote(bid=1.0999, ask=1.1001)
        self.instrument = instrument or InstrumentInfo("EUR_USD", tick_size=0.00001, step_size=1,
                                                       min_size=1, quote_currency="USD")
        self.balance = balance
        self.can_short = can_short
        self.positions = {}
        self.opened, self.closed, self.reconciled = [], [], []

    def get_candles(self, symbol, granularity, count):
        return None if self.candles is None else self.candles.tail(count).reset_index(drop=True)

    def get_quote(self, symbol):
        return self.quote

    def get_instrument(self, symbol):
        return self.instrument

    def get_balance(self):
        return self.balance

    def get_position(self, symbol):
        return self.positions.get(symbol)

    def open_position(self, order):
        self.opened.append(order)
        p = Position(order.symbol, order.side, order.size, order.entry_estimate,
                     order.stop_loss, order.take_profit, id=str(len(self.opened)))
        self.positions[order.symbol] = p
        return OrderResult(True, p)

    def close_position(self, symbol):
        self.closed.append(symbol)
        self.positions.pop(symbol, None)
        return True

    def reconcile(self, symbol, granularity):
        self.reconciled.append(symbol)


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    """Stands in for requests.Session; routes are {(METHOD, path): FakeResponse or Exception}."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, params=None, headers=None, data=None, timeout=None):
        path = url.split("/v3", 1)[1]
        self.calls.append({"method": method, "path": path, "params": params,
                           "headers": headers, "body": json.loads(data) if data else None})
        route = self.routes[(method, path)]
        if isinstance(route, Exception):
            raise route
        return route


def spot_market(symbol="BTC/USDT", tick=0.01, step=0.00001, min_cost=5.0, order_types=None):
    base, quote = symbol.split("/")
    return {"id": base + quote, "symbol": symbol, "base": base, "quote": quote,
            "precision": {"amount": step, "price": tick},
            "limits": {"amount": {"min": step}, "cost": {"min": min_cost}},
            "info": {"orderTypes": order_types or ["LIMIT", "LIMIT_MAKER", "MARKET", "STOP_LOSS", "STOP_LOSS_LIMIT"]}}


def futures_market(symbol="ETH/USDT:USDT", tick=0.01, step=0.001, min_cost=20.0):
    return {"id": symbol.split("/")[0] + "USDT", "symbol": symbol, "base": symbol.split("/")[0],
            "quote": "USDT", "precision": {"amount": step, "price": tick},
            "limits": {"amount": {"min": step}, "cost": {"min": min_cost}}, "info": {}}


class FakeExchange:
    """Records ccxt calls made by the Binance brokers."""

    def __init__(self, markets, balances=None, fill_price=None, fees=None, oco_error=None,
                 open_orders=None, positions=None, setting_errors=None, conditional_error=None):
        self.markets = markets
        self.balances = balances or {}
        self.fill_price = fill_price
        self.fees = fees or []
        self.oco_error = oco_error
        self.open_orders = open_orders or []
        self.positions = positions or []
        self.setting_errors = setting_errors or {}
        self.conditional_error = conditional_error
        self.calls = []

    def load_markets(self):
        return self.markets

    def market(self, symbol):
        return self.markets[symbol]

    def amount_to_precision(self, symbol, amount):
        return str(floor_to_step(amount, self.markets[symbol]["precision"]["amount"]))

    def price_to_precision(self, symbol, price):
        return str(round_to_step(price, self.markets[symbol]["precision"]["price"]))

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        params = params or {}
        self.calls.append(("create_order", symbol, type, side, amount, params))
        if self.conditional_error and ("stopLossPrice" in params or "takeProfitPrice" in params):
            raise self.conditional_error
        return {"id": str(len(self.calls)), "filled": amount, "average": self.fill_price, "fees": self.fees}

    def private_post_orderlist_oco(self, params):
        self.calls.append(("oco", params))
        if self.oco_error:
            raise self.oco_error
        return {"orderListId": 77}

    def private_delete_orderlist(self, params):
        self.calls.append(("cancel_list", params))
        return {}

    def fetch_open_orders(self, symbol=None, since=None, limit=None, params=None):
        self.calls.append(("fetch_open_orders", symbol, params))
        return self.open_orders

    def fetch_balance(self):
        return self.balances

    def fetch_positions(self, symbols=None):
        return self.positions

    def cancel_all_orders(self, symbol=None, params=None):
        self.calls.append(("cancel_all", symbol, params))
        return []

    def _setting(self, name, *args):
        self.calls.append((name,) + args)
        if name in self.setting_errors:
            raise self.setting_errors[name]

    def set_position_mode(self, hedged, symbol=None):
        self._setting("set_position_mode", hedged, symbol)

    def set_margin_mode(self, mode, symbol=None):
        self._setting("set_margin_mode", mode, symbol)

    def set_leverage(self, leverage, symbol=None):
        self._setting("set_leverage", leverage, symbol)

    def made(self, name):
        return [c for c in self.calls if c[0] == name]
