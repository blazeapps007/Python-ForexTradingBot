import math
from dataclasses import dataclass

from brokers.base import Order
from defs import BUY, SELL
from indicators import atr
from precision import floor_to_step, round_to_step

MAX_RISK_PCT = 5.0


class RiskError(Exception):
    """The decision can't be turned into a safe order."""


@dataclass
class RiskSettings:
    risk_pct: float = 1.0           # % of balance lost if the stop loss is hit
    atr_period: int = 14
    sl_atr_mult: float = 1.5        # stop loss distance = sl_atr_mult x ATR
    rr: float = 2.0                 # take profit distance = rr x stop loss distance
    max_open_positions: int = 5
    min_sl_spreads: float = 2.0     # stop loss must be at least this many bid/ask spreads away


def sl_tp_from_atr(side, entry, atr_value, sl_atr_mult, rr):
    distance = atr_value * sl_atr_mult
    if side == BUY:
        return entry - distance, entry + distance * rr
    return entry + distance, entry - distance * rr


def build_order(decision, *, symbol, candles, quote, instrument, balance, open_positions, settings, max_size=None):
    """Turn a strategy Decision into an Order with stop loss, take profit and a risk-based size.

    Raises RiskError when any guardrail fails. Every order, whatever strategy produced it,
    passes through here.
    """
    if not 0 < settings.risk_pct <= MAX_RISK_PCT:
        raise RiskError(f"risk_pct {settings.risk_pct} must be > 0 and <= {MAX_RISK_PCT}")
    if open_positions >= settings.max_open_positions:
        raise RiskError(f"{open_positions} positions open, limit is {settings.max_open_positions}")
    side = decision.signal
    if side not in (BUY, SELL):
        raise RiskError("decision has no BUY/SELL signal")
    if quote.quote_to_account is None:
        raise RiskError(f"can't convert {instrument.quote_currency} to the account currency for sizing")

    entry = quote.ask if side == BUY else quote.bid
    stop_loss, take_profit = decision.stop_loss, decision.take_profit
    if stop_loss is None:
        atr_value = atr(candles, settings.atr_period).iloc[-1]
        if math.isnan(atr_value) or atr_value <= 0:
            raise RiskError(f"ATR({settings.atr_period}) unavailable, need more candles")
        stop_loss, _ = sl_tp_from_atr(side, entry, atr_value, settings.sl_atr_mult, settings.rr)
    if take_profit is None:
        distance = abs(entry - stop_loss) * settings.rr
        take_profit = entry + distance if side == BUY else entry - distance

    stop_loss = round_to_step(stop_loss, instrument.tick_size)
    take_profit = round_to_step(take_profit, instrument.tick_size)
    if side == BUY and not stop_loss < entry < take_profit:
        raise RiskError(f"BUY needs SL < entry < TP, got {stop_loss} / {entry} / {take_profit}")
    if side == SELL and not take_profit < entry < stop_loss:
        raise RiskError(f"SELL needs TP < entry < SL, got {take_profit} / {entry} / {stop_loss}")
    spread = quote.ask - quote.bid
    if abs(entry - stop_loss) < spread * settings.min_sl_spreads:
        raise RiskError(f"stop loss {abs(entry - stop_loss):.6g} away is closer than "
                        f"{settings.min_sl_spreads} x spread ({spread:.6g}); market too quiet for this timeframe")

    risk_amount = balance * settings.risk_pct / 100
    risk_per_unit = abs(entry - stop_loss) * quote.quote_to_account
    size = risk_amount / risk_per_unit
    if max_size is not None:
        size = min(size, max_size)
    size = floor_to_step(size, instrument.step_size)

    if size < instrument.min_size:
        raise RiskError(f"size {size} below minimum {instrument.min_size} "
                        f"(risk {risk_amount:.2f}, SL distance {abs(entry - stop_loss):.6g})")
    if size * entry < instrument.min_notional:
        raise RiskError(f"order value {size * entry:.2f} below minimum {instrument.min_notional}")

    return Order(symbol=symbol, side=side, size=size, entry_estimate=entry,
                 stop_loss=stop_loss, take_profit=take_profit,
                 risk_amount=size * risk_per_unit, reason=decision.reason)
