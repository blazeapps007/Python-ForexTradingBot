# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Forex trading project built against the OANDA v20 REST API (practice endpoint `api-fxpractice.oanda.com`). Commits follow a course-style `#NN - <topic>` numbering. The repo holds three **independent** Python sub-projects. Each one has its own copies of `defs.py`, `oanda_api.py` and `utils.py`, and those copies have diverged. Nothing is shared between them, so a change to one project's `oanda_api.py` does not affect the others.

| Directory | Purpose |
|---|---|
| repo root | Research and backtesting: historical data collection, strategy simulations, Jupyter notebooks |
| `TradingBotStarter/` | Live trading bot: moving-average crossover on M1 candles, places real orders on the practice account |
| `WebDashStarter/` | Flask and Vue 2 dashboard showing indicator and candle-pattern KPIs for 21 pairs |

There are no tests, linters or build steps.

## Environment

- The code targets Python 3.11 and pandas 1.5.x. `ma_excel.py` calls `ExcelWriter.save()`, which was removed in pandas 2.0.
- The `venv/` directories committed at the root and in each sub-project were created on another machine (`pyvenv.cfg` points to `C:\Users\Mathew\...`). They won't work as-is, so recreate them locally:
  - `python -m venv venv; venv\Scripts\activate; pip install -r requirements.txt` (in `TradingBotStarter/` or `WebDashStarter/`)
  - The root has no `requirements.txt`. Its venv holds pandas, requests, python-dateutil, plotly, xlsxwriter and jupyter.
- There is no `.gitignore`. `venv/`, `__pycache__/`, `logs/`, `.pkl` data and generated outputs are all tracked, so avoid `git add -A` and stage files explicitly.
- OANDA credentials are hardcoded in each sub-project's `defs.py`. `WebDashStarter/.env` only sets Flask variables.

## Running

Every script uses paths relative to the current directory (`his_data/`, `instruments.pkl`, `settings.json`, `./logs`, `data.json`). Run each one from inside its own directory.

**Root (research):**
- `python collect_his_data.py` downloads M5, H1 and H4 candles for 2020-01-01 to 2022-12-31 into `his_data/{PAIR}_{GRAN}.pkl`, in 2000-candle chunks. It requires `instruments.pkl`, which you can create with `OandaAPI().save_instruments()` or `instrument.ipynb`.
- `python ma_sim.py` runs the MA-crossover grid search on H1 data and writes `ma_test_res.pkl`, `all_trades.pkl` and `ma_results.xlsx`.
- `python ma_excel.py` rebuilds `ma_results.xlsx` from the two existing pickles.
- `python inside_bar_sim.py` runs the inside-bar momentum backtest. H4 signals are replayed against M5 bid/ask prices.
- Start Jupyter from the repo root, because the notebooks `import utils`, `instrument` and `defs` from there.

**TradingBotStarter:**
- `python bot.py` runs the live bot loop.
- `python runner.py` opens an interactive manual-trade REPL: `T` opens a 1000-unit EUR_USD trade, `C` closes it, `Q` quits.
- `python oanda_api.py` prints open trades. `python settings.py` prints the loaded settings.

**WebDashStarter:** the dashboard needs two processes.
- `python run_tasks.py` regenerates `data.json` every minute using `schedule`.
- `flask run` or `python app.py` serves the API and the `static/` frontend.

## Shared conventions

- Pair names use OANDA format (`EUR_USD`). The test universe is the currencies `"GBP,EUR,USD,CAD,JPY,NZD,CHF"`. They are expanded into all `A_B` combinations that exist in `instruments.pkl`, which gives 21 pairs. See `Instrument.get_pairs_from_string`; `ma_sim.py` and `inside_bar_sim.py` each keep their own duplicate `get_test_pairs`.
- Candle DataFrames come from `OandaAPI.candles_to_df`. Their columns are `time`, `volume` and `{mid,bid,ask}_{o,h,l,c}` (WebDash fetches `mid` only). Incomplete candles are dropped and `time` is parsed to a tz-aware UTC datetime.
- Direction and signal values are `BUY = 1`, `SELL = -1`, `NONE = 0`. They are multiplied by `units` to get the signed order size.
- `Instrument.pipLocation` is stored as `10 ** pipLocation` (for example `-4` becomes `0.0001`). `ma_sim` measures gains in pips. `inside_bar_sim` measures gains as multiples of the stop distance (TP/SL = 0.8/0.4, so a win scores +2 and a loss −1).

## Data flow (root)

`instrument.ipynb` / `OandaAPI.save_instruments()` → `instruments.pkl` → `collect_his_data.py` → `his_data/*.pkl` → `ma_sim.py` / `inside_bar_sim.py` / notebooks.
`inside_bar_explore*.ipynb` writes `USD_JPY_H4_trades.pkl`, which `inside_bar_timings*.ipynb` reads. `ma_sim_explorer.ipynb` and `candle_plot.ipynb` read the `ma_sim` output pickles. The `*_spread` notebook variants use bid/ask prices instead of mid.

## Live bot architecture (TradingBotStarter)

`TradingBot.run()` polls every 10 seconds:
1. `update_timings()`: for each pair in `settings.json`, a `Timing` object tracks the last complete M1 candle time and sets `ready` when a newer one appears.
2. `process_pairs()`: for each ready pair, `Technicals.get_trade_decision()` fetches `long_ma + 2` candles. It rejects the batch if the last candle's time doesn't match the expected candle, then computes the short/long MA cross and returns BUY, SELL or NONE.
3. `TradeManager.place_trades()`: for each pair with a signal, it **closes every open trade on that pair**, then opens a new market order (FOK). The bot is therefore always in the market and reverses on each cross.

Per-pair parameters (`units`, `short_ma`, `long_ma`) live in `settings.json`. Logs go to `./logs/Bot.log`, `Technicals.log` and `Trade.log`. They are opened with mode `"w"`, so each start overwrites them.

Quirks in `TradingBotStarter/oanda_api.py` that affect behaviour:
- `fetch_candles` ignores its `count` argument and always requests 10 candles. As a result `long_ma` above ~8 never yields both MA values, and the bot never trades.
- `place_trade` returns `None` on HTTP failure but a `(trade_id, ok)` tuple on success. `TradeManager.create_trades` treats the return value as a bare trade id.
- `make_request` writes `added_headers` into the module-level `defs.SECURE_HEADER` dict, which changes it for every later request.

## Web dashboard architecture (WebDashStarter)

- `data_prep.py` fetches 100 M1 candles for each pair in `PAIRS`. It applies MACD cross, Bollinger signal, EMA 8/20/50 trend and candle patterns (hammer, doji, marubozu, spinning top, engulfing), then writes the **last row** for each pair to `WebDashStarter/data.json`. The thresholds are module constants. The logic was prototyped in the root `candle_indicators.ipynb` and `candle_patterns.ipynb`.
- `app.py` serves three things: `GET /kpi_data` returns `data.json` as written; `GET /price_data/<pair>` returns 50 live M5 candles as column lists for Plotly; and WhiteNoise serves `static/`.
- `static/app.js` is a Vue 2 app with Plotly, both loaded from CDN with no build step. It polls `/kpi_data` every 15 seconds and draws a candlestick chart when you click a row. The column names in `DF_COLS` must match the `item.<FIELD>` bindings in `static/index.html`.
- `static/data.json` is an empty, unused file. The live file is `WebDashStarter/data.json`.
