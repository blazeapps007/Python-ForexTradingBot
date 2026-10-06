import os

import ccxt

from brokers.binance_futures import BinanceFuturesBroker
from brokers.binance_spot import BinanceSpotBroker
from brokers.ccxt_common import make_exchange
from brokers.oanda import OandaBroker
from brokers.paper import PaperAccount, PaperBroker


def spot_symbol(futures_symbol):
    """ETH/USDT:USDT -> ETH/USDT"""
    return futures_symbol.split(":")[0]


def build_brokers(config):
    """One broker per broker name used in settings.json. In paper mode each is a PaperBroker
    reading live prices from the real data source."""
    names = {inst.broker for inst in config.instruments}
    leverage = {inst.symbol: inst.leverage for inst in config.instruments if inst.broker == "binance_futures"}

    if config.trading_mode == "paper":
        account = PaperAccount(config.paper_balance,
                               state_file=os.path.join(config.log_dir, "paper_state.json"),
                               trades_file=os.path.join(config.log_dir, "paper_trades.csv"))
        brokers = {}
        for name in names:
            if name == "oanda":
                brokers[name] = PaperBroker(name, _oanda(config), account)
            elif name == "binance_spot":
                brokers[name] = PaperBroker(name, _spot_prices(), account)
            elif name == "binance_futures":
                # perpetual prices are approximated by the spot price of the same pair
                brokers[name] = PaperBroker(name, _spot_prices(), account, can_short=True,
                                            symbol_map=spot_symbol, leverage=leverage)
        return brokers

    brokers = {}
    for name in names:
        if name == "oanda":
            brokers[name] = _oanda(config)
        elif name == "binance_spot":
            exchange = make_exchange(ccxt.binance, config.binance_api_key, config.binance_api_secret,
                                     config.binance_env, ["spot"])
            brokers[name] = BinanceSpotBroker(exchange, state_file=os.path.join(config.log_dir, "binance_spot_state.json"))
        elif name == "binance_futures":
            exchange = make_exchange(ccxt.binanceusdm, config.binance_futures_api_key,
                                     config.binance_futures_api_secret, config.binance_env, ["linear"])
            brokers[name] = BinanceFuturesBroker(exchange, leverage=leverage)
    return brokers


def _oanda(config):
    return OandaBroker(config.oanda_api_key, config.oanda_account_id, config.oanda_env)


def _spot_prices():
    # no API keys: this exchange object can read prices but cannot trade
    return BinanceSpotBroker(make_exchange(ccxt.binance, None, None, "data", ["spot"]))
