import logging

from defs import BUY, NONE, SELL
from risk import RiskError, build_order

log = logging.getLogger(__name__)

SIDE_NAMES = {BUY: "BUY", SELL: "SELL", NONE: "NONE"}


class TradeManager():
    """One position per instrument. Same-direction signals are ignored; an opposite signal
    closes the position and opens the new one (on spot, a SELL only exits)."""

    def process(self, inst, broker, strategy, candles, count_open_positions):
        position = broker.get_position(inst.symbol)
        decision = strategy.decide(candles, position)
        log.info("%s %s: %s", inst.key, SIDE_NAMES[decision.signal], decision.reason)

        if decision.signal == NONE:
            return "no_signal"
        if position is not None and position.side == decision.signal:
            return "hold"

        if position is not None:
            if not broker.close_position(inst.symbol):
                log.error("%s failed to close %s position", inst.key, SIDE_NAMES[position.side])
                return "close_failed"
            log.info("%s closed %s position on opposite signal", inst.key, SIDE_NAMES[position.side])

        if decision.signal == SELL and not broker.can_short:
            return "exited" if position is not None else "skip_short"

        quote = broker.get_quote(inst.symbol)
        instrument = broker.get_instrument(inst.symbol)
        balance = broker.get_balance()
        if quote is None or instrument is None or balance is None:
            log.error("%s missing quote, instrument or balance, not trading", inst.key)
            return "no_data"

        entry = quote.ask if decision.signal == BUY else quote.bid
        try:
            order = build_order(decision, symbol=inst.symbol, candles=candles, quote=quote,
                                instrument=instrument, balance=balance,
                                open_positions=count_open_positions(), settings=inst.risk,
                                max_size=broker.max_size(inst.symbol, decision.signal, entry))
        except RiskError as e:
            log.warning("%s order rejected by risk check: %s", inst.key, e)
            return "rejected"

        log.info("%s placing %s %s @ ~%s SL %s TP %s risk %.2f",
                 inst.key, SIDE_NAMES[order.side], order.size, order.entry_estimate,
                 order.stop_loss, order.take_profit, order.risk_amount)
        result = broker.open_position(order)
        if not result.ok:
            log.error("%s open failed: %s", inst.key, result.error)
            return "open_failed"
        p = result.position
        log.info("%s opened %s %s @ %s SL %s TP %s id %s",
                 inst.key, SIDE_NAMES[p.side], p.size, p.entry_price, p.stop_loss, p.take_profit, p.id)
        return "opened"
