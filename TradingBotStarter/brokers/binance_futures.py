import logging

from brokers.base import OrderResult, Position
from brokers.ccxt_common import CcxtBroker
from defs import BUY, SELL

log = logging.getLogger(__name__)

# keep some margin back for fees and price moves
MARGIN_BUFFER = 0.95


class BinanceFuturesBroker(CcxtBroker):
    """Binance USD-M perpetual futures (symbols like ETH/USDT:USDT), one-way mode, isolated margin.

    Entry is a market order; the stop loss and take profit are reduce-only conditional
    orders, which ccxt sends to Binance's algo-order endpoint.
    """
    name = "binance_futures"
    can_short = True

    def __init__(self, exchange, account_asset="USDT", leverage=None):
        super().__init__(exchange, account_asset)
        self.leverage = leverage or {}
        self._prepared = set()

    def _prepare(self, symbol):
        if symbol in self._prepared:
            return
        ex = self.exchange
        steps = (
            lambda: ex.set_position_mode(False, symbol),
            lambda: ex.set_margin_mode("isolated", symbol),
            lambda: ex.set_leverage(self.leverage.get(symbol, 1), symbol),
        )
        for step in steps:
            try:
                step()
            except Exception as e:
                # Binance answers "No need to change ..." when the setting is already in place
                if "No need to change" not in str(e):
                    raise
        self._prepared.add(symbol)

    def get_balance(self):
        return self._asset_balance(self.account_asset, "total")

    def max_size(self, symbol, side, entry):
        free = self._asset_balance(self.account_asset, "free")
        return free * self.leverage.get(symbol, 1) * MARGIN_BUFFER / entry

    def get_position(self, symbol):
        for p in self.exchange.fetch_positions([symbol]):
            contracts = float(p.get("contracts") or 0)
            if contracts and p.get("symbol") == symbol:
                return Position(symbol, BUY if p.get("side") == "long" else SELL, contracts,
                                float(p.get("entryPrice") or 0))
        return None

    def open_position(self, order):
        self._prepare(order.symbol)
        ex = self.exchange
        side, exit_side = ("buy", "sell") if order.side == BUY else ("sell", "buy")
        amount = float(ex.amount_to_precision(order.symbol, order.size))
        entry = ex.create_order(order.symbol, "market", side, amount)
        average = float(entry.get("average") or order.entry_estimate)

        # keep the planned SL/TP distances, measured from the actual fill price
        shift = average - order.entry_estimate
        stop_loss = float(ex.price_to_precision(order.symbol, order.stop_loss + shift))
        take_profit = float(ex.price_to_precision(order.symbol, order.take_profit + shift))

        try:
            ex.create_order(order.symbol, "market", exit_side, amount, None,
                            {"stopLossPrice": stop_loss, "reduceOnly": True})
            ex.create_order(order.symbol, "market", exit_side, amount, None,
                            {"takeProfitPrice": take_profit, "reduceOnly": True})
        except Exception as e:
            log.error("%s SL/TP placement failed, closing position: %s", order.symbol, e)
            if not self.close_position(order.symbol):
                log.critical("%s UNPROTECTED POSITION: close failed", order.symbol)
            return OrderResult(False, error=f"SL/TP failed: {e}")

        return OrderResult(True, Position(order.symbol, order.side, amount, average, stop_loss, take_profit,
                                          id=str(entry.get("id"))))

    def close_position(self, symbol):
        try:
            self.exchange.cancel_all_orders(symbol, {"trigger": True})
        except Exception as e:
            log.warning("%s cancel SL/TP orders: %s", symbol, e)
        position = self.get_position(symbol)
        if position is None:
            return True
        exit_side = "sell" if position.side == BUY else "buy"
        try:
            self.exchange.create_order(symbol, "market", exit_side, position.size, None, {"reduceOnly": True})
        except Exception as e:
            log.error("%s close failed: %s", symbol, e)
            return False
        return True

    def reconcile(self, symbol, granularity):
        if self.get_position(symbol) is not None:
            return
        # position closed by SL or TP: cancel the leftover exit order
        if self.exchange.fetch_open_orders(symbol, None, None, {"trigger": True}):
            log.info("%s position closed by SL/TP, cancelling the remaining exit order", symbol)
            self.exchange.cancel_all_orders(symbol, {"trigger": True})
