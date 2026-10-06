# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A trading project with three **independent** Python sub-projects. Commits follow a course-style `#NN - <topic>` numbering. Each sub-project has its own `defs.py` and broker code, and nothing is shared between them.

| Directory | Purpose |
|---|---|
| repo root | Research and backtesting on OANDA Forex data: historical data collection, strategy simulations, Jupyter notebooks |
| `TradingBotStarter/` | Multi-broker trading bot (OANDA, Binance spot including bStocks, Binance USDⓈ-M futures) with ATR SL/TP and risk-% sizing. Runs in Docker, paper mode by default |
| `WebDashStarter/` | Flask and Vue 2 dashboard showing indicator and candle-pattern KPIs for 21 Forex pairs |

`README.md` documents the strategy rules, recorded backtest results, broker endpoints, configuration and step-by-step extension guides. Keep it in sync when behaviour changes.

## Testing and running: Docker only

The user tests **only in Docker** on their local PC. Never run python, pip or pytest on the Windows host; it has no real Python install anyway, only the Microsoft Store alias. All commands run from the repo root:

```bash
docker compose build                                   # rebuild the bot image after code changes
docker compose run --rm tests                          # unit tests (offline, ~2 s)
docker compose run --rm tests pytest tests/test_risk.py::test_buy_sl_tp_from_atr_and_risk_sized   # one test
docker compose run --rm tests pytest -m integration -rs   # network tests against broker test environments
docker compose up bot                                  # run the bot (TRADING_MODE from .env, default paper)
```

- The `tests` service bind-mounts `TradingBotStarter/` at `/app`, so it sees edits without a rebuild. The `bot` service uses the built image.
- In Git Bash, prefix commands that pass container paths (e.g. `-e SETTINGS_FILE=/app/...`) with `MSYS_NO_PATHCONV=1`, or Git Bash rewrites them into Windows paths.
- `pytest.ini` deselects `integration` tests by default. Integration tests that place orders skip unless practice/testnet keys are in `.env`, and they never run against live environments.
- Some networks DNS-block `*.binance.com`. `testnet.binance.vision`, `testnet.binancefuture.com` and `data-api.binance.vision` usually stay reachable; that is why `BINANCE_ENV` defaults to `testnet` and paper mode reads prices from the data mirror.

## Trading bot architecture (TradingBotStarter)

Pipeline per instrument, on each new complete candle (`bot.py` → `trade_manager.py`):
1. `broker.reconcile()`
2. `strategy.decide(candles, position)`, which returns a `Decision`
3. `TradeManager` applies the position rules: same-direction signal = hold; opposite signal = close, then open (on spot, SELL only exits)
4. `risk.build_order()`
5. `broker.open_position()`

**Invariant: strategies never place orders.** Every `Decision`, including a future Amazon Bedrock AI strategy, must go through `risk.build_order()`, which:
- fills in SL/TP from ATR (`sl_atr_mult × ATR`, TP = `rr ×` the stop distance);
- sizes by `risk_pct` of the balance, using the `Quote.quote_to_account` conversion;
- rounds to tick and step size;
- raises `RiskError` on unsafe orders: wrong-side SL/TP, a stop closer than `min_sl_spreads × spread`, below the minimum size or notional, `max_open_positions` reached, `risk_pct > 5`.

- `brokers/base.py` defines the `Broker` interface and the `Order` / `Position` / `Quote` / `InstrumentInfo` dataclasses. `brokers/factory.py` builds one broker per broker name used in `settings.json`. In paper mode each is wrapped in a `PaperBroker` that reads real prices and simulates fills.
- `get_position()` must raise `BrokerError` when the state is unknown, rather than return `None`, so the bot never opens a duplicate.
- `open_position()` must attach the SL and TP, or undo the entry:
  - **OANDA:** `stopLossOnFill` / `takeProfitOnFill` in the market order.
  - **Binance spot:** market buy, then an OCO via `private_post_orderlist_oco`; if the OCO fails, it sells back.
  - **Binance futures:** market entry, then reduce-only `stopLossPrice` / `takeProfitPrice` orders, which ccxt routes to the algo-order endpoint; if they fail, it closes the position.
- Binance spot tracks only bot-opened positions in `logs/binance_spot_state.json`, so pre-existing coins are never sold.
- Config:
  - `settings.json` holds instruments, strategy params and risk settings: a `defaults` block merged into each instrument, with `"enabled": false` to switch one off.
  - Environment variables hold the mode and secrets: `TRADING_MODE`, `OANDA_*`, `BINANCE_*`, optional `BINANCE_FUTURES_*`, `ALLOW_REAL_MONEY`. `.env.example` lists them.
  - `config.py` validates everything and refuses any `live` environment in broker mode unless `ALLOW_REAL_MONEY=yes`.
- New strategy: subclass `strategies.base.Strategy` and register it in `strategies/__init__.py` `STRATEGIES`. New broker: implement `Broker` (subclass `brokers.ccxt_common.CcxtBroker` for ccxt exchanges), add it to `BROKERS` in `config.py`, and build it in `brokers/factory.py`.
- Tests use fakes in `tests/helpers.py`: `FakeBroker`, `FakeExchange` (ccxt), `FakeSession` (requests), and candle builders.
- Pinned versions: `ccxt==4.5.85` and `pandas==3.0.6` on Python 3.12. The Binance broker code depends on that ccxt version's implicit endpoint names, for example `private_post_orderlist_oco`.
- These old OANDA-only modules are unused leftovers: `oanda_api.py`, `oanda_trade.py`, `technicals.py`, `settings.py`, `timing.py`, `utils.py`, `runner.py`. `defs.py` now only holds `BUY`/`SELL`/`NONE`.

## Research scripts (repo root)

These were not containerized yet; they target Python 3.11 and pandas 1.5.x. `ma_excel.py` calls `ExcelWriter.save()`, which was removed in pandas 2.0. The committed `venv/` folders point at another machine (`C:\Users\Mathew\...`) and don't work. Every script uses paths relative to its own directory.

- `python collect_his_data.py` downloads M5, H1 and H4 candles for 2020-01-01 to 2022-12-31 into `his_data/{PAIR}_{GRAN}.pkl`, in 2000-candle chunks. It needs `instruments.pkl`, from `OandaAPI().save_instruments()` or `instrument.ipynb`.
- `ma_sim.py` runs the MA grid search and writes `ma_test_res.pkl`, `all_trades.pkl` and `ma_results.xlsx`. `inside_bar_sim.py` replays H4 inside-bar signals on M5 bid/ask prices. Notebooks import `utils`, `instrument` and `defs` from the root.
- Pair names use OANDA format. The test universe is the currencies `"GBP,EUR,USD,CAD,JPY,NZD,CHF"`, expanded into the 21 `A_B` pairs that exist in `instruments.pkl` (`Instrument.get_pairs_from_string`).
- Candle frames come from `OandaAPI.candles_to_df`: `time`, `volume`, `{mid,bid,ask}_{o,h,l,c}`. `Instrument.pipLocation` is stored as `10 ** pipLocation`.
- The current `his_data/*.pkl` files store `time` as tz-aware datetimes (since #45). `ma_sim.py`, `candle_plot.ipynb` and `inside_bar_timings*.ipynb` call `dateutil.parse()` on it, which fails on these files.
- `inside_bar_explore*.ipynb` writes `USD_JPY_H4_trades.pkl`, which `inside_bar_timings*.ipynb` reads.
- The root and `WebDashStarter` `defs.py` still hardcode an OANDA key.

## Web dashboard (WebDashStarter)

It needs two processes: `python run_tasks.py`, which regenerates `data.json` every minute, and `flask run`, configured by `.env`.

- `data_prep.py` computes MACD cross, Bollinger signal, EMA 8/20/50 trend and candle patterns on the last 100 M1 candles per pair, and writes the last row per pair to `data.json`.
- `app.py` serves `/kpi_data`, `/price_data/<pair>` (50 M5 candles) and `static/` via WhiteNoise.
- `DF_COLS` must match the `item.<FIELD>` bindings in `static/index.html`.
- Pattern cells never highlight: the fields are booleans, but `applyDirectionClass()` only matches `1`/`-1`. `applyOnOffClass()` exists but is unused.
- `static/data.json` is an unused empty file.

## Git hygiene

`.gitignore` covers `.env`, `__pycache__/` and `TradingBotStarter/logs/`. Files tracked before it existed (`venv/`, `__pycache__/`, old logs, pickles) are still in the index. Avoid `git add -A`; stage files explicitly.
