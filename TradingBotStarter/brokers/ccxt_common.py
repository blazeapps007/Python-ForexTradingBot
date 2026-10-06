import time

import pandas as pd

from brokers.base import GRANULARITY_SECONDS, Broker, InstrumentInfo, Quote

TIMEFRAMES = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "D": "1d"}

# Binance's public market-data mirror: live spot prices, no trading
SPOT_DATA_MIRROR = "https://data-api.binance.vision/api/v3"


def make_exchange(exchange_class, api_key, secret, env, market_types):
    """Build a ccxt exchange for one Binance environment.

    env: "testnet" (testnet.binance.vision / testnet.binancefuture.com), "demo" (demo.binance.com),
    "live", or "data" (read-only live spot prices from the public mirror).
    """
    exchange = exchange_class({
        "apiKey": api_key or None,
        "secret": secret or None,
        "enableRateLimit": True,
        "options": {"fetchMarkets": {"types": market_types}},
    })
    if env == "testnet":
        exchange.set_sandbox_mode(True)
    elif env == "demo":
        exchange.enable_demo_trading(True)
    elif env == "data":
        exchange.urls["api"]["public"] = SPOT_DATA_MIRROR
    elif env != "live":
        raise ValueError(f"unknown Binance environment {env!r}")
    return exchange


def ohlcv_to_df(rows, granularity, now_ms=None):
    """ccxt OHLCV rows -> candle DataFrame, dropping the candle that is still forming."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    duration_ms = GRANULARITY_SECONDS[granularity] * 1000
    complete = [r for r in rows if r[0] + duration_ms <= now_ms]
    df = pd.DataFrame(complete, columns=["ts", "mid_o", "mid_h", "mid_l", "mid_c", "volume"])
    df["time"] = pd.to_datetime(df.ts, unit="ms", utc=True)
    return df[["time", "volume", "mid_o", "mid_h", "mid_l", "mid_c"]].reset_index(drop=True)


class CcxtBroker(Broker):
    """Market data shared by the Binance spot and futures brokers."""

    def __init__(self, exchange, account_asset="USDT"):
        self.exchange = exchange
        self.account_asset = account_asset
        self._markets_loaded = False

    def market(self, symbol):
        if not self._markets_loaded:
            self.exchange.load_markets()
            self._markets_loaded = True
        return self.exchange.market(symbol)

    def get_candles(self, symbol, granularity, count):
        # one extra, because the candle still forming is dropped
        rows = self.exchange.fetch_ohlcv(symbol, TIMEFRAMES[granularity], limit=count + 1)
        return ohlcv_to_df(rows, granularity).tail(count).reset_index(drop=True)

    def get_quote(self, symbol):
        book = self.exchange.fetch_order_book(symbol, limit=5)
        if not book["bids"] or not book["asks"]:
            return None
        quote_ccy = self.market(symbol)["quote"]
        return Quote(bid=float(book["bids"][0][0]), ask=float(book["asks"][0][0]),
                     quote_to_account=1.0 if quote_ccy == self.account_asset else None)

    def get_instrument(self, symbol):
        market = self.market(symbol)
        limits = market.get("limits", {})
        step = float(market["precision"]["amount"])
        return InstrumentInfo(
            symbol=symbol,
            tick_size=float(market["precision"]["price"]),
            step_size=step,
            min_size=float((limits.get("amount") or {}).get("min") or step),
            min_notional=float((limits.get("cost") or {}).get("min") or 0.0),
            quote_currency=market["quote"],
        )

    def _asset_balance(self, asset, kind="free"):
        balance = self.exchange.fetch_balance()
        return float((balance.get(asset) or {}).get(kind) or 0.0)
