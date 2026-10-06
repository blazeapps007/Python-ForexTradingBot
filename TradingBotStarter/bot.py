import logging
import sys
import time

from brokers.factory import build_brokers
from config import ConfigError, load_config
from log_wrapper import setup_logging
from strategies import build_strategy
from trade_manager import TradeManager

log = logging.getLogger("bot")


class TradingBot():

    def __init__(self, config, brokers, trade_manager=None, sleep=time.sleep):
        self.config = config
        self.brokers = brokers
        self.strategies = {inst.key: build_strategy(inst.strategy, inst.params) for inst in config.instruments}
        self.last_candle = {inst.key: None for inst in config.instruments}
        self.trade_manager = trade_manager or TradeManager()
        self.sleep = sleep

    def count_open_positions(self):
        return sum(1 for inst in self.config.instruments
                   if self.brokers[inst.broker].get_position(inst.symbol) is not None)

    def process(self, inst):
        broker = self.brokers[inst.broker]
        latest = broker.last_complete_candle_time(inst.symbol, inst.granularity)
        if latest is None:
            return "no_data"

        previous = self.last_candle[inst.key]
        if previous is None:
            # first look after start-up: trade from the next new candle, not this one
            self.last_candle[inst.key] = latest
            log.info("%s watching %s candles, last complete %s", inst.key, inst.granularity, latest)
            return "warmup"
        if latest <= previous:
            return "waiting"
        self.last_candle[inst.key] = latest

        broker.reconcile(inst.symbol, inst.granularity)
        strategy = self.strategies[inst.key]
        count = max(strategy.required_candles(), inst.risk.atr_period + 1) + 2
        candles = broker.get_candles(inst.symbol, inst.granularity, count)
        if candles is None or candles.empty or candles.time.iloc[-1] != latest:
            log.warning("%s candles not ready for %s, retrying", inst.key, latest)
            self.last_candle[inst.key] = previous
            return "stale_candles"

        return self.trade_manager.process(inst, broker, strategy, candles, self.count_open_positions)

    def run_once(self):
        actions = {}
        for inst in self.config.instruments:
            try:
                actions[inst.key] = self.process(inst)
            except Exception:
                # one bad request must not stop the bot; try again on the next loop
                log.exception("%s error, skipping this cycle", inst.key)
                actions[inst.key] = "error"
        return actions

    def run(self):
        log.info("Bot started: mode=%s, instruments=%s", self.config.trading_mode,
                 ", ".join(i.key for i in self.config.instruments))
        while True:
            self.run_once()
            self.sleep(self.config.poll_seconds)


def main():
    try:
        config = load_config()
    except (ConfigError, FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(2)
    setup_logging(config.log_dir)
    log.info("Environments: OANDA=%s, Binance=%s", config.oanda_env, config.binance_env)
    TradingBot(config, build_brokers(config)).run()


if __name__ == "__main__":
    main()
