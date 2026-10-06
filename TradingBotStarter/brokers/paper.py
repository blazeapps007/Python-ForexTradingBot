import csv
import json
import logging
import os
from datetime import datetime, timezone

import pandas as pd

from brokers.base import GRANULARITY_SECONDS, Broker, OrderResult, Position
from defs import BUY

log = logging.getLogger(__name__)


class PaperAccount:
    """Simulated balance and open positions, shared by all paper brokers and saved to disk."""

    def __init__(self, starting_balance, state_file=None, trades_file=None):
        self.state_file = state_file
        self.trades_file = trades_file
        if state_file and os.path.exists(state_file):
            with open(state_file) as f:
                saved = json.load(f)
            self.balance = float(saved["balance"])
            self.positions = saved["positions"]
        else:
            self.balance = float(starting_balance)
            self.positions = {}

    def save(self):
        if self.state_file:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump({"balance": self.balance, "positions": self.positions}, f, indent=2)

    def record_trade(self, row):
        if not self.trades_file:
            return
        os.makedirs(os.path.dirname(self.trades_file) or ".", exist_ok=True)
        new_file = not os.path.exists(self.trades_file)
        with open(self.trades_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row))
            if new_file:
                writer.writeheader()
            writer.writerow(row)


def exit_hit(side, candle, stop_loss, take_profit):
    """Return (reason, price) if this candle hit the stop loss or take profit.

    Longs exit on the bid and shorts on the ask when those columns exist. If both
    levels fall inside one candle, the stop loss is assumed to have hit first.
    """
    prefix = ("bid" if side == BUY else "ask") if "bid_l" in candle else "mid"
    high, low, open_ = candle[f"{prefix}_h"], candle[f"{prefix}_l"], candle[f"{prefix}_o"]
    if side == BUY:
        if low <= stop_loss:
            return "stop_loss", min(stop_loss, open_)   # a gap down fills at the open
        if high >= take_profit:
            return "take_profit", take_profit
    else:
        if high >= stop_loss:
            return "stop_loss", max(stop_loss, open_)
        if low <= take_profit:
            return "take_profit", take_profit
    return None, None


class PaperBroker(Broker):
    """Trades on paper using another broker's live market data. Never sends orders."""

    def __init__(self, name, data_broker, account, can_short=None, symbol_map=None, leverage=None):
        self.name = name
        self.data = data_broker
        self.account = account
        self.can_short = data_broker.can_short if can_short is None else can_short
        self.symbol_map = symbol_map or (lambda symbol: symbol)
        self.leverage = leverage   # {symbol: leverage} for futures, None otherwise

    def _key(self, symbol):
        return f"{self.name}:{symbol}"

    def get_candles(self, symbol, granularity, count):
        return self.data.get_candles(self.symbol_map(symbol), granularity, count)

    def get_quote(self, symbol):
        return self.data.get_quote(self.symbol_map(symbol))

    def get_instrument(self, symbol):
        return self.data.get_instrument(self.symbol_map(symbol))

    def get_balance(self):
        return self.account.balance

    def max_size(self, symbol, side, entry):
        if self.leverage is not None:
            return self.account.balance * self.leverage.get(symbol, 1) / entry
        if not self.can_short:
            return self.account.balance / entry   # spot: cash only
        return None

    def get_position(self, symbol):
        p = self.account.positions.get(self._key(symbol))
        if p is None:
            return None
        return Position(symbol, p["side"], p["size"], p["entry"], p["stop_loss"], p["take_profit"], id=self._key(symbol))

    def open_position(self, order):
        quote = self.get_quote(order.symbol)
        if quote is None:
            return OrderResult(False, error="no quote")
        fill = quote.ask if order.side == BUY else quote.bid
        shift = fill - order.entry_estimate
        p = {
            "side": order.side, "size": order.size, "entry": fill,
            "stop_loss": order.stop_loss + shift, "take_profit": order.take_profit + shift,
            "quote_to_account": quote.quote_to_account or 1.0,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "checked_until": None,   # time of the last candle already checked for SL/TP
        }
        self.account.positions[self._key(order.symbol)] = p
        self.account.save()
        log.info("[paper] %s filled %s %s @ %s", order.symbol, "BUY" if order.side == BUY else "SELL", order.size, fill)
        return OrderResult(True, self.get_position(order.symbol))

    def close_position(self, symbol):
        p = self.account.positions.get(self._key(symbol))
        if p is None:
            return True
        quote = self.get_quote(symbol)
        if quote is None:
            return False
        self._close(symbol, quote.bid if p["side"] == BUY else quote.ask, "signal")
        return True

    def _close(self, symbol, price, reason):
        key = self._key(symbol)
        p = self.account.positions.pop(key)
        pnl = (price - p["entry"]) * p["side"] * p["size"] * p["quote_to_account"]
        self.account.balance += pnl
        self.account.save()
        self.account.record_trade({
            "closed_at": datetime.now(timezone.utc).isoformat(), "broker": self.name, "symbol": symbol,
            "side": "BUY" if p["side"] == BUY else "SELL", "size": p["size"], "entry": p["entry"],
            "exit": price, "reason": reason, "pnl": round(pnl, 2), "balance": round(self.account.balance, 2),
        })
        log.info("[paper] %s closed by %s @ %s, pnl %.2f, balance %.2f", symbol, reason, price, pnl, self.account.balance)

    def reconcile(self, symbol, granularity):
        p = self.account.positions.get(self._key(symbol))
        if p is None:
            return
        candles = self.get_candles(symbol, granularity, 50)
        if candles is None or candles.empty:
            return
        if p.get("checked_until"):
            candles = candles[candles.time > pd.Timestamp(p["checked_until"])]
        else:
            # first check: every candle that ended after the fill
            duration = pd.Timedelta(seconds=GRANULARITY_SECONDS[granularity])
            candles = candles[candles.time + duration > pd.Timestamp(p["opened_at"])]
        for _, candle in candles.iterrows():
            reason, price = exit_hit(p["side"], candle, p["stop_loss"], p["take_profit"])
            if reason:
                self._close(symbol, price, reason)
                return
        if not candles.empty:
            p["checked_until"] = candles.time.iloc[-1].isoformat()
            self.account.save()
