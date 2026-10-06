import json
import logging

import pandas as pd
import requests

from brokers.base import Broker, BrokerError, InstrumentInfo, OrderResult, Position, Quote
from defs import BUY, SELL
from precision import decimals

log = logging.getLogger(__name__)

OANDA_URLS = {
    "practice": "https://api-fxpractice.oanda.com/v3",
    "live": "https://api-fxtrade.oanda.com/v3",
}


class OandaBroker(Broker):
    name = "oanda"
    can_short = True

    def __init__(self, api_key, account_id, env="practice", session=None):
        self.base_url = OANDA_URLS[env]
        self.account_id = account_id
        self.session = session or requests.Session()
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        self._instruments = None
        self._account_currency = None

    def request(self, method, path, params=None, body=None, ok_codes=(200,)):
        """Return (data, error): the JSON body on success, otherwise None and a message."""
        try:
            response = self.session.request(
                method, self.base_url + path, params=params,
                headers=dict(self.headers),
                data=json.dumps(body) if body is not None else None,
                timeout=20)
        except requests.RequestException as e:
            return None, f"{method} {path} failed: {e}"

        try:
            data = response.json()
        except ValueError:
            data = None

        if response.status_code in ok_codes:
            return data, ""
        message = data.get("errorMessage") if isinstance(data, dict) else None
        return None, f"{method} {path} -> {response.status_code}: {message or response.text[:200]}"

    def account_path(self, suffix):
        return f"/accounts/{self.account_id}{suffix}"

    def get_candles(self, symbol, granularity, count):
        # one extra, because the candle still forming is dropped
        data, error = self.request("GET", f"/instruments/{symbol}/candles",
                                   params={"granularity": granularity, "price": "MBA", "count": count + 1})
        if data is None:
            log.error(error)
            return None
        return self.candles_to_df(data.get("candles", [])).tail(count).reset_index(drop=True)

    @staticmethod
    def candles_to_df(candles):
        rows = []
        for candle in candles:
            if not candle.get("complete", False):
                continue
            row = {"time": candle["time"], "volume": candle["volume"]}
            for price in ("mid", "bid", "ask"):
                if price in candle:
                    for oh in "ohlc":
                        row[f"{price}_{oh}"] = float(candle[price][oh])
            rows.append(row)
        df = pd.DataFrame(rows)
        if not df.empty:
            df["time"] = pd.to_datetime(df.time, utc=True)
        return df

    def _load_instruments(self):
        if self._instruments is None:
            data, error = self.request("GET", self.account_path("/instruments"))
            if data is None:
                log.error(error)
                return {}
            self._instruments = {i["name"]: i for i in data["instruments"]}
        return self._instruments

    def get_instrument(self, symbol):
        raw = self._load_instruments().get(symbol)
        if raw is None:
            return None
        return InstrumentInfo(
            symbol=symbol,
            tick_size=10 ** -int(raw["displayPrecision"]),
            step_size=10 ** -int(raw.get("tradeUnitsPrecision", 0)),
            min_size=float(raw.get("minimumTradeSize", 1)),
            quote_currency=symbol.split("_")[1],
        )

    def _summary(self):
        data, error = self.request("GET", self.account_path("/summary"))
        if data is None:
            log.error(error)
            return None
        account = data["account"]
        self._account_currency = account.get("currency")
        return account

    def get_balance(self):
        account = self._summary()
        return float(account["NAV"]) if account else None

    def get_quote(self, symbol):
        data, error = self.request("GET", self.account_path("/pricing"),
                                   params={"instruments": symbol, "includeHomeConversions": "true"})
        if not data or not data.get("prices"):
            log.error(error or f"no price for {symbol}")
            return None
        price = data["prices"][0]
        return Quote(bid=float(price["bids"][0]["price"]),
                     ask=float(price["asks"][0]["price"]),
                     quote_to_account=self._loss_conversion(symbol, data, price))

    def _loss_conversion(self, symbol, data, price):
        """Factor turning a loss in the pair's quote currency into the account currency."""
        quote_ccy = symbol.split("_")[1]
        for conversion in data.get("homeConversions", []):
            if conversion.get("currency") == quote_ccy and "accountLoss" in conversion:
                return float(conversion["accountLoss"])
        factors = price.get("quoteHomeConversionFactors")
        if factors:
            return max(float(factors["positiveUnits"]), float(factors["negativeUnits"]))
        if self._account_currency is None:
            self._summary()
        return 1.0 if quote_ccy == self._account_currency else None

    def _open_trades(self, symbol):
        data, error = self.request("GET", self.account_path("/openTrades"))
        if data is None:
            raise BrokerError(error)
        return [t for t in data.get("trades", []) if t["instrument"] == symbol]

    def get_position(self, symbol):
        trades = self._open_trades(symbol)
        units = sum(float(t["currentUnits"]) for t in trades)
        if units == 0:
            return None
        first = trades[0]
        return Position(
            symbol=symbol,
            side=BUY if units > 0 else SELL,
            size=abs(units),
            entry_price=float(first["price"]),
            stop_loss=float(first["stopLossOrder"]["price"]) if "stopLossOrder" in first else None,
            take_profit=float(first["takeProfitOrder"]["price"]) if "takeProfitOrder" in first else None,
            id=",".join(t["id"] for t in trades),
        )

    def open_position(self, order):
        info = self.get_instrument(order.symbol)
        if info is None:
            return OrderResult(False, error=f"unknown instrument {order.symbol}")
        price_dp = decimals(info.tick_size)
        units_dp = decimals(info.step_size)

        # stop loss and take profit are attached to the fill, so the trade is never unprotected
        body = {
            "order": {
                "type": "MARKET",
                "instrument": order.symbol,
                "units": f"{order.size * order.side:.{units_dp}f}",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{order.stop_loss:.{price_dp}f}", "timeInForce": "GTC"},
                "takeProfitOnFill": {"price": f"{order.take_profit:.{price_dp}f}", "timeInForce": "GTC"},
            }
        }
        data, error = self.request("POST", self.account_path("/orders"), body=body, ok_codes=(201,))
        if data is None:
            return OrderResult(False, error=error)

        fill = data.get("orderFillTransaction", {})
        opened = fill.get("tradeOpened")
        if not opened:
            reason = data.get("orderCancelTransaction", {}).get("reason", "order was not filled")
            return OrderResult(False, error=reason)

        return OrderResult(True, Position(
            symbol=order.symbol,
            side=order.side,
            size=abs(float(opened["units"])),
            entry_price=float(fill.get("price", order.entry_estimate)),
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            id=str(opened["tradeID"]),
        ))

    def close_position(self, symbol):
        ok = True
        for trade in self._open_trades(symbol):
            data, error = self.request("PUT", self.account_path(f"/trades/{trade['id']}/close"))
            if data is None:
                log.error(error)
                ok = False
        return ok
