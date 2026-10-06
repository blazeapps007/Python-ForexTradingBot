import json
import logging
import os
from dataclasses import dataclass, field

from brokers.base import GRANULARITY_SECONDS
from risk import MAX_RISK_PCT, RiskSettings
from strategies import STRATEGIES

log = logging.getLogger(__name__)

BROKERS = ("oanda", "binance_spot", "binance_futures")
BINANCE_BROKERS = ("binance_spot", "binance_futures")


class ConfigError(Exception):
    pass


@dataclass
class InstrumentConfig:
    broker: str
    symbol: str
    strategy: str
    params: dict
    granularity: str
    risk: RiskSettings
    leverage: int = 1

    @property
    def key(self):
        return f"{self.broker}:{self.symbol}"


@dataclass
class AppConfig:
    instruments: list = field(default_factory=list)
    trading_mode: str = "paper"          # paper | broker
    poll_seconds: float = 10.0
    paper_balance: float = 10000.0
    log_dir: str = "logs"
    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_env: str = "practice"          # practice | live
    binance_api_key: str = ""
    binance_api_secret: str = ""
    # futures keys default to the spot ones; the spot and futures testnets issue separate keys
    binance_futures_api_key: str = ""
    binance_futures_api_secret: str = ""
    binance_env: str = "testnet"         # testnet | demo | live
    allow_real_money: bool = False


def load_config(settings_path=None, env=None):
    """Read settings.json (strategy and risk settings) and environment variables (mode, secrets)."""
    env = os.environ if env is None else env
    path = settings_path or env.get("SETTINGS_FILE", "settings.json")
    with open(path) as f:
        raw = json.load(f)

    defaults = raw.get("defaults", {})
    instruments = [_instrument(item, defaults) for item in raw.get("instruments", [])
                   if item.get("enabled", True)]

    config = AppConfig(
        instruments=instruments,
        trading_mode=env.get("TRADING_MODE", "paper").lower(),
        poll_seconds=float(raw.get("poll_seconds", 10)),
        paper_balance=float(raw.get("paper", {}).get("starting_balance", 10000)),
        log_dir=env.get("LOG_DIR", "logs"),
        oanda_api_key=env.get("OANDA_API_KEY", ""),
        oanda_account_id=env.get("OANDA_ACCOUNT_ID", ""),
        oanda_env=env.get("OANDA_ENV", "practice").lower(),
        binance_api_key=env.get("BINANCE_API_KEY", ""),
        binance_api_secret=env.get("BINANCE_API_SECRET", ""),
        binance_futures_api_key=env.get("BINANCE_FUTURES_API_KEY") or env.get("BINANCE_API_KEY", ""),
        binance_futures_api_secret=env.get("BINANCE_FUTURES_API_SECRET") or env.get("BINANCE_API_SECRET", ""),
        binance_env=env.get("BINANCE_ENV", "testnet").lower(),
        allow_real_money=env.get("ALLOW_REAL_MONEY", "no").lower() in ("yes", "true", "1"),
    )
    _validate(config)
    return config


def _instrument(item, defaults):
    merged = {**defaults, **item}
    for key in ("broker", "symbol", "strategy"):
        if key not in merged:
            raise ConfigError(f"instrument {item} is missing '{key}'")
    risk = RiskSettings(
        risk_pct=float(merged.get("risk_pct", 1.0)),
        atr_period=int(merged.get("atr_period", 14)),
        sl_atr_mult=float(merged.get("sl_atr_mult", 1.5)),
        rr=float(merged.get("rr", 2.0)),
        max_open_positions=int(merged.get("max_open_positions", 5)),
        min_sl_spreads=float(merged.get("min_sl_spreads", 2.0)),
    )
    return InstrumentConfig(
        broker=merged["broker"], symbol=merged["symbol"], strategy=merged["strategy"],
        params=merged.get("params", {}), granularity=merged.get("granularity", "M5"),
        risk=risk, leverage=int(merged.get("leverage", 1)),
    )


def _validate(config):
    if config.trading_mode not in ("paper", "broker"):
        raise ConfigError(f"TRADING_MODE must be paper or broker, got {config.trading_mode!r}")
    if config.oanda_env not in ("practice", "live"):
        raise ConfigError(f"OANDA_ENV must be practice or live, got {config.oanda_env!r}")
    if config.binance_env not in ("testnet", "demo", "live"):
        raise ConfigError(f"BINANCE_ENV must be testnet, demo or live, got {config.binance_env!r}")

    seen = set()
    for inst in config.instruments:
        if inst.broker not in BROKERS:
            raise ConfigError(f"{inst.symbol}: unknown broker {inst.broker!r}, use one of {BROKERS}")
        if inst.strategy not in STRATEGIES:
            raise ConfigError(f"{inst.symbol}: unknown strategy {inst.strategy!r}, use one of {list(STRATEGIES)}")
        if inst.granularity not in GRANULARITY_SECONDS:
            raise ConfigError(f"{inst.symbol}: unknown granularity {inst.granularity!r}")
        if not 0 < inst.risk.risk_pct <= MAX_RISK_PCT:
            raise ConfigError(f"{inst.symbol}: risk_pct must be > 0 and <= {MAX_RISK_PCT}")
        if inst.risk.sl_atr_mult <= 0 or inst.risk.rr <= 0:
            raise ConfigError(f"{inst.symbol}: sl_atr_mult and rr must be positive")
        if inst.leverage < 1:
            raise ConfigError(f"{inst.symbol}: leverage must be at least 1")
        if inst.key in seen:
            raise ConfigError(f"{inst.key} is listed twice")
        seen.add(inst.key)

    has_oanda_keys = bool(config.oanda_api_key and config.oanda_account_id)
    has_spot_keys = bool(config.binance_api_key and config.binance_api_secret)
    has_futures_keys = bool(config.binance_futures_api_key and config.binance_futures_api_secret)

    if config.trading_mode == "paper":
        # paper prices for OANDA still come from the OANDA API; Binance prices need no keys
        skipped = [i.key for i in config.instruments if i.broker == "oanda" and not has_oanda_keys]
        if skipped:
            log.warning("Skipping %s: OANDA_API_KEY / OANDA_ACCOUNT_ID not set", ", ".join(skipped))
            config.instruments = [i for i in config.instruments if i.key not in skipped]
    else:
        uses = {i.broker for i in config.instruments}
        if "oanda" in uses and not has_oanda_keys:
            raise ConfigError("OANDA instruments need OANDA_API_KEY and OANDA_ACCOUNT_ID")
        if "binance_spot" in uses and not has_spot_keys:
            raise ConfigError("Binance spot instruments need BINANCE_API_KEY and BINANCE_API_SECRET")
        if "binance_futures" in uses and not has_futures_keys:
            raise ConfigError("Binance futures instruments need BINANCE_FUTURES_API_KEY/SECRET "
                              "(or BINANCE_API_KEY/SECRET)")
        real_money = ("oanda" in uses and config.oanda_env == "live") or \
                     (uses & set(BINANCE_BROKERS) and config.binance_env == "live")
        if real_money and not config.allow_real_money:
            raise ConfigError("a live (real money) environment is selected; set ALLOW_REAL_MONEY=yes to confirm")

    if not config.instruments:
        raise ConfigError("no instruments to trade (check settings.json and your API keys)")
