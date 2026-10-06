import json
import logging
import os

from brokers.base import OrderResult, Position
from brokers.ccxt_common import CcxtBroker
from defs import BUY

log = logging.getLogger(__name__)

# limit price offset below the stop, used only when a symbol doesn't allow plain STOP_LOSS orders
STOP_LIMIT_SLIPPAGE = 0.002
# keep some quote balance back for trading fees
FEE_BUFFER = 0.99


class BinanceSpotBroker(CcxtBroker):
    """Binance spot: crypto pairs and bStocks (tokenized stocks such as TSLAB/USDT).

    Long-only. A position is a market buy protected by an OCO sell: a take-profit
    LIMIT_MAKER above and a stop loss below. Only positions the bot opened are tracked
    (in state_file), so coins already in the account are never sold by the bot.
    """
    name = "binance_spot"
    can_short = False

    def __init__(self, exchange, account_asset="USDT", state_file=None):
        super().__init__(exchange, account_asset)
        self.state_file = state_file
        self.state = self._load_state()

    def _load_state(self):
        if self.state_file and os.path.exists(self.state_file):
            with open(self.state_file) as f:
                return json.load(f)
        return {}

    def _save_state(self):
        if self.state_file:
            os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)

    def get_balance(self):
        return self._asset_balance(self.account_asset)

    def max_size(self, symbol, side, entry):
        return self.get_balance() * FEE_BUFFER / entry

    def get_position(self, symbol):
        s = self.state.get(symbol)
        if s is None:
            return None
        return Position(symbol, BUY, s["size"], s["entry"], s["stop_loss"], s["take_profit"],
                        id=str(s.get("order_list_id") or ""))

    def open_position(self, order):
        if order.side != BUY:
            return OrderResult(False, error="spot is long-only")
        ex = self.exchange
        amount = float(ex.amount_to_precision(order.symbol, order.size))
        filled_order = ex.create_order(order.symbol, "market", "buy", amount)

        filled = float(filled_order.get("filled") or amount)
        average = float(filled_order.get("average") or order.entry_estimate)
        held = ex.amount_to_precision(order.symbol, filled - self._fee_in_base(order.symbol, filled_order))

        # keep the planned SL/TP distances, measured from the actual fill price
        shift = average - order.entry_estimate
        stop_loss = float(ex.price_to_precision(order.symbol, order.stop_loss + shift))
        take_profit = float(ex.price_to_precision(order.symbol, order.take_profit + shift))

        try:
            response = self._place_oco(order.symbol, held, stop_loss, take_profit)
        except Exception as e:
            log.error("%s OCO failed after buy, selling back: %s", order.symbol, e)
            try:
                ex.create_order(order.symbol, "market", "sell", held)
            except Exception as sell_error:
                log.critical("%s UNPROTECTED POSITION: sell-back failed: %s", order.symbol, sell_error)
                self.state[order.symbol] = {"size": float(held), "entry": average, "stop_loss": None,
                                            "take_profit": None, "order_list_id": None}
                self._save_state()
            return OrderResult(False, error=f"OCO failed: {e}")

        self.state[order.symbol] = {
            "size": float(held), "entry": average, "stop_loss": stop_loss,
            "take_profit": take_profit, "order_list_id": response.get("orderListId"),
        }
        self._save_state()
        return OrderResult(True, Position(order.symbol, BUY, float(held), average, stop_loss, take_profit,
                                          id=str(response.get("orderListId"))))

    def _fee_in_base(self, symbol, order):
        base = self.market(symbol)["base"]
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        return sum(float(f.get("cost") or 0) for f in fees if f and f.get("currency") == base)

    def _place_oco(self, symbol, quantity, stop_loss, take_profit):
        market = self.market(symbol)
        ex = self.exchange
        order_types = market["info"].get("orderTypes", [])
        below_type = "STOP_LOSS" if "STOP_LOSS" in order_types else "STOP_LOSS_LIMIT"
        params = {
            "symbol": market["id"],
            "side": "SELL",
            "quantity": quantity,
            "aboveType": "LIMIT_MAKER",
            "abovePrice": ex.price_to_precision(symbol, take_profit),
            "belowType": below_type,
            "belowStopPrice": ex.price_to_precision(symbol, stop_loss),
        }
        if below_type == "STOP_LOSS_LIMIT":
            params["belowPrice"] = ex.price_to_precision(symbol, stop_loss * (1 - STOP_LIMIT_SLIPPAGE))
            params["belowTimeInForce"] = "GTC"
        return ex.private_post_orderlist_oco(params)

    def close_position(self, symbol):
        s = self.state.get(symbol)
        if s is None:
            return True
        market = self.market(symbol)
        if s.get("order_list_id") is not None:
            try:
                self.exchange.private_delete_orderlist({"symbol": market["id"], "orderListId": s["order_list_id"]})
            except Exception as e:
                log.warning("%s cancel OCO %s: %s", symbol, s["order_list_id"], e)
            s["order_list_id"] = None
            self._save_state()

        amount = min(s["size"], self._asset_balance(market["base"]))
        info = self.get_instrument(symbol)
        if amount >= info.min_size:
            try:
                self.exchange.create_order(symbol, "market", "sell",
                                           float(self.exchange.amount_to_precision(symbol, amount)))
            except Exception as e:
                log.error("%s exit sell failed: %s", symbol, e)
                return False
        del self.state[symbol]
        self._save_state()
        return True

    def reconcile(self, symbol, granularity):
        s = self.state.get(symbol)
        if s is None or s.get("order_list_id") is None:
            return
        open_orders = self.exchange.fetch_open_orders(symbol)
        list_id = str(s["order_list_id"])
        if not any(str(o.get("info", {}).get("orderListId")) == list_id for o in open_orders):
            log.info("%s exit order filled (stop loss or take profit), position closed", symbol)
            del self.state[symbol]
            self._save_state()
