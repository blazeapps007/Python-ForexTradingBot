import json

import pytest

from config import ConfigError, load_config

KEYS = {"OANDA_API_KEY": "k", "OANDA_ACCOUNT_ID": "a", "BINANCE_API_KEY": "k", "BINANCE_API_SECRET": "s"}


def write(tmp_path, instruments, defaults=None):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"defaults": defaults or {"strategy": "ma_cross"}, "instruments": instruments}))
    return str(path)


def test_defaults_merge_into_instruments(tmp_path):
    path = write(tmp_path, [{"broker": "binance_spot", "symbol": "BTC/USDT", "risk_pct": 0.5}],
                 defaults={"strategy": "ma_cross", "granularity": "H1", "params": {"short_ma": 5, "long_ma": 20}})
    inst = load_config(path, env={}).instruments[0]
    assert (inst.granularity, inst.params["long_ma"], inst.risk.risk_pct, inst.risk.rr) == ("H1", 20, 0.5, 2.0)
    assert inst.key == "binance_spot:BTC/USDT"


def test_paper_is_the_default_mode(tmp_path):
    config = load_config(write(tmp_path, [{"broker": "binance_spot", "symbol": "BTC/USDT"}]), env={})
    assert config.trading_mode == "paper" and config.binance_env == "testnet"


def test_paper_skips_oanda_without_keys(tmp_path):
    path = write(tmp_path, [{"broker": "oanda", "symbol": "EUR_USD"}, {"broker": "binance_spot", "symbol": "BTC/USDT"}])
    assert [i.symbol for i in load_config(path, env={}).instruments] == ["BTC/USDT"]


def test_disabled_instruments_are_ignored(tmp_path):
    path = write(tmp_path, [{"broker": "binance_spot", "symbol": "BTC/USDT"},
                            {"broker": "binance_spot", "symbol": "ETH/USDT", "enabled": False}])
    assert len(load_config(path, env={}).instruments) == 1


def test_broker_mode_needs_keys(tmp_path):
    path = write(tmp_path, [{"broker": "binance_futures", "symbol": "ETH/USDT:USDT"}])
    with pytest.raises(ConfigError, match="BINANCE_API_KEY"):
        load_config(path, env={"TRADING_MODE": "broker"})


def test_futures_keys_fall_back_to_spot_keys(tmp_path):
    path = write(tmp_path, [{"broker": "binance_futures", "symbol": "ETH/USDT:USDT"}])
    shared = load_config(path, env={**KEYS, "TRADING_MODE": "broker"})
    assert shared.binance_futures_api_key == "k"
    separate = load_config(path, env={"TRADING_MODE": "broker", "BINANCE_FUTURES_API_KEY": "fk",
                                      "BINANCE_FUTURES_API_SECRET": "fs"})
    assert (separate.binance_futures_api_key, separate.binance_futures_api_secret) == ("fk", "fs")


def test_live_needs_explicit_confirmation(tmp_path):
    path = write(tmp_path, [{"broker": "oanda", "symbol": "EUR_USD"}])
    env = {**KEYS, "TRADING_MODE": "broker", "OANDA_ENV": "live"}
    with pytest.raises(ConfigError, match="ALLOW_REAL_MONEY"):
        load_config(path, env=env)
    assert load_config(path, env={**env, "ALLOW_REAL_MONEY": "yes"}).oanda_env == "live"


@pytest.mark.parametrize("instrument, message", [
    ({"broker": "kraken", "symbol": "X"}, "unknown broker"),
    ({"broker": "oanda", "symbol": "EUR_USD", "strategy": "magic"}, "unknown strategy"),
    ({"broker": "oanda", "symbol": "EUR_USD", "granularity": "M3"}, "granularity"),
    ({"broker": "oanda", "symbol": "EUR_USD", "risk_pct": 10}, "risk_pct"),
    ({"broker": "oanda", "symbol": "EUR_USD", "leverage": 0}, "leverage"),
])
def test_invalid_settings(tmp_path, instrument, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, [instrument]), env=KEYS)


def test_repository_settings_file_loads():
    config = load_config("settings.json", env={})
    assert {i.broker for i in config.instruments} == {"binance_spot", "binance_futures"}
