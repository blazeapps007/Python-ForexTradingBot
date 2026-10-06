from strategies.base import Decision, Strategy
from strategies.ma_cross import MACrossStrategy

STRATEGIES = {
    MACrossStrategy.name: MACrossStrategy,
}


def build_strategy(name, params=None):
    return STRATEGIES[name](params)
