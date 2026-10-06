from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

GRANULARITY_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D": 86400,
}


class BrokerError(Exception):
    """A broker call failed in a way that makes the current state unknown."""


@dataclass
class InstrumentInfo:
    symbol: str
    tick_size: float        # smallest price increment
    step_size: float        # smallest size increment
    min_size: float
    min_notional: float = 0.0
    quote_currency: str = ""


@dataclass
class Quote:
    bid: float
    ask: float
    # multiply an amount in the quote currency by this to get the account currency;
    # None when the broker can't convert, and risk sizing then refuses the order
    quote_to_account: float | None = 1.0


@dataclass
class Order:
    symbol: str
    side: int               # BUY or SELL
    size: float             # always positive
    entry_estimate: float
    stop_loss: float
    take_profit: float
    risk_amount: float = 0.0
    reason: str = ""


@dataclass
class Position:
    symbol: str
    side: int
    size: float
    entry_price: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    id: str = ""


@dataclass
class OrderResult:
    ok: bool
    position: Position | None = None
    error: str = ""


class Broker(ABC):
    name = "base"
    can_short = True

    @abstractmethod
    def get_candles(self, symbol, granularity, count) -> pd.DataFrame | None:
        """Complete candles only, oldest first. Columns: time (UTC), volume,
        mid_o, mid_h, mid_l, mid_c, and bid_*/ask_* where the broker provides them."""

    @abstractmethod
    def get_quote(self, symbol) -> Quote | None:
        ...

    @abstractmethod
    def get_instrument(self, symbol) -> InstrumentInfo | None:
        ...

    @abstractmethod
    def get_balance(self) -> float | None:
        """Balance used for risk sizing, in the account currency."""

    @abstractmethod
    def get_position(self, symbol) -> Position | None:
        """The bot's open position on symbol, or None. Raises BrokerError if it can't tell."""

    @abstractmethod
    def open_position(self, order: Order) -> OrderResult:
        """Open a position with its stop loss and take profit attached."""

    @abstractmethod
    def close_position(self, symbol) -> bool:
        ...

    def max_size(self, symbol, side, entry) -> float | None:
        """Largest size the account can fund, or None for no extra limit."""
        return None

    def reconcile(self, symbol, granularity) -> None:
        """Called on every new candle before deciding: tidy up after SL/TP exits."""

    def last_complete_candle_time(self, symbol, granularity):
        df = self.get_candles(symbol, granularity, 2)
        if df is None or df.empty:
            return None
        return df.time.iloc[-1]
