from abc import ABC, abstractmethod
from dataclasses import dataclass

from defs import NONE


@dataclass
class Decision:
    signal: int = NONE
    # optional: when left as None, risk.py sets them from ATR
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""


class Strategy(ABC):
    """A trading strategy turns recent candles into a Decision.

    Strategies never place orders themselves: every Decision goes through risk.build_order(),
    which enforces the stop loss, take profit and position size. A future AI strategy (for
    example one calling an Amazon Bedrock model) implements this same interface.
    """
    name = "base"

    def __init__(self, params=None):
        self.params = dict(params or {})

    @abstractmethod
    def required_candles(self) -> int:
        """How many complete candles decide() needs."""

    @abstractmethod
    def decide(self, candles, position=None) -> Decision:
        """candles: DataFrame of complete candles, oldest first. position: the open Position or None."""
