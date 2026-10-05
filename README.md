# Python Forex Trading Bot

This project uses several tools to build an automated Forex trading strategy. It backtests strategies on real historical Forex data, monitors the market through a live indicator dashboard, and runs a bot that places trades automatically through the OANDA broker API.

> **Warning:** the live bot sends real market orders to whichever OANDA account is set in `TradingBotStarter/defs.py`. It has no stop loss, take profit or risk controls. Run it on a **practice** account.

---

## Contents

1. [Project overview](#1-project-overview)
2. [Repository layout](#2-repository-layout)
3. [Setup](#3-setup)
4. [Connecting to the broker (OANDA)](#4-connecting-to-the-broker-oanda)
5. [Historical data pipeline](#5-historical-data-pipeline)
6. [Strategies](#6-strategies)
7. [Live trading bot](#7-live-trading-bot)
8. [Web dashboard](#8-web-dashboard)
9. [API reference](#9-api-reference)
10. [Extending the project](#10-extending-the-project)
11. [Known issues and limitations](#11-known-issues-and-limitations)

---

## 1. Project overview

The repository has three parts. Each is a self-contained Python project with its own `defs.py` (credentials), `oanda_api.py` (broker client) and `utils.py`. The copies differ from each other, so a change to one does not affect the others.

| Part | Folder | What it does |
|---|---|---|
| **Research and backtesting** | repo root | Downloads historical candles from OANDA, backtests the moving-average crossover and inside-bar momentum strategies, exports results to Excel, and explores ideas in Jupyter notebooks |
| **Live trading bot** | [`TradingBotStarter/`](TradingBotStarter/) | Watches 1-minute candles for a set of pairs and trades moving-average crossovers on the OANDA account |
| **Indicator dashboard** | [`WebDashStarter/`](WebDashStarter/) | A Flask and Vue web page showing MACD, Bollinger Band, trend and candle-pattern signals for 21 pairs, with live candlestick charts |

Typical workflow: collect data → backtest in the root project → set the chosen parameters in the bot's `settings.json` → run the bot. The dashboard can run alongside to watch the market.

The commit history follows numbered lessons (`#NN - <topic>`), so the code reads as a step-by-step build.

---

## 2. Repository layout

```
.
├── defs.py                  # OANDA credentials and URL (research copy)
├── oanda_api.py             # OANDA client: instruments, historical candles by count or date range
├── instrument.py            # Instrument class (pip size, margin) loaded from instruments.pkl
├── utils.py                 # data file names, UTC date helpers
├── collect_his_data.py      # downloads M5/H1/H4 candles for 2020-2022 into his_data/
├── ma_sim.py                # moving-average crossover grid backtest
├── ma_result.py             # result summary object used by ma_sim.py
├── ma_excel.py              # writes ma_results.xlsx (one sheet and chart per pair)
├── inside_bar_sim.py        # inside-bar momentum backtest (H4 signals replayed on M5 prices)
├── *.ipynb                  # exploration notebooks (table below)
├── his_data/                # 63 candle files: 21 pairs x M5/H1/H4 (about 600 MB)
├── instruments.pkl          # OANDA instrument list
├── ma_test_res.pkl, all_trades.pkl, ma_results.xlsx   # ma_sim.py output
├── USD_JPY_H4_trades.pkl    # inside-bar signals written by the explore notebooks
│
├── TradingBotStarter/
│   ├── bot.py               # TradingBot main loop (entry point)
│   ├── settings.json        # pairs to trade and strategy parameters per pair
│   ├── settings.py          # loads settings.json
│   ├── timing.py            # tracks the last complete candle for each pair
│   ├── technicals.py        # strategy: MA crossover decision on the latest candles
│   ├── trade_manager.py     # closes and opens trades on OANDA
│   ├── oanda_api.py         # OANDA client: candles, orders, trades
│   ├── oanda_trade.py       # OandaTrade: parsed open-trade object
│   ├── log_wrapper.py       # file logger writing to ./logs/<name>.log
│   ├── runner.py            # manual console for opening and closing a test trade
│   ├── defs.py, utils.py, requirements.txt
│   └── logs/
│
└── WebDashStarter/
    ├── app.py               # Flask server: static site and JSON endpoints
    ├── data_prep.py         # computes indicators and patterns, writes data.json
    ├── run_tasks.py         # reruns data_prep every minute
    ├── oanda_api.py         # OANDA client: mid-price candles, chart data
    ├── data.json            # latest KPI snapshot served to the page
    ├── static/              # index.html, app.js (Vue 2), styles.css
    ├── .env                 # FLASK_APP=app.py, FLASK_DEBUG=1
    └── defs.py, requirements.txt
```

### Notebooks

| Notebook | Purpose |
|---|---|
| `test.ipynb` | First candles request to OANDA, step by step; saves `EUR_USD_H1.pkl` |
| `instrument.ipynb` | Fetches the instrument list and saves `instruments.pkl` |
| `save_candles.ipynb` | Early data collection: the last 4,000 H1 candles for each pair |
| `candle_plot.ipynb` | Plotly candlestick chart with moving averages; analyses the EUR_USD 16/64 crossover |
| `ma_sim_explorer.ipynb` | Analyses `ma_sim.py` output: best crossovers and cumulative-gain charts |
| `inside_bar_explore.ipynb` | Finds inside-bar signals on USD_JPY H4 and simulates them on H4 closes |
| `inside_bar_explore_spread.ipynb` | Same as above, with entries placed from bid/ask extremes |
| `inside_bar_timings.ipynb` | Replays the inside-bar trades on M5 mid prices |
| `inside_bar_timings_spread.ipynb` | Replays the inside-bar trades on M5 bid/ask prices (the logic used in `inside_bar_sim.py`) |
| `candle_patterns.ipynb` | Prototype of the candle-pattern rules used by the dashboard |
| `candle_indicators.ipynb` | Prototype of Bollinger Bands and MACD |

Start Jupyter from the repo root, because the notebooks import `utils`, `defs` and `instrument` from there.

---

## 3. Setup

**Requirements:** Python 3.11 and an OANDA account (a free practice account works; see [section 4](#4-connecting-to-the-broker-oanda)).

The `venv/` folders in the repository were created on another computer and won't work on yours. Create a fresh environment instead. One environment at the repo root can serve all three parts:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install "pandas<2" "numpy<2" requests python-dateutil plotly xlsxwriter jupyter flask python-dotenv whitenoise schedule
```

`pandas<2` is needed because `ma_excel.py` calls `ExcelWriter.save()`, which pandas 2.0 removed. If you only want one part, `TradingBotStarter/requirements.txt` and `WebDashStarter/requirements.txt` list that part's own dependencies.

**Every script uses paths relative to the folder it runs in** (`his_data/`, `settings.json`, `logs/`, `data.json`), so always `cd` into a project's folder before running its scripts.

---

## 4. Connecting to the broker (OANDA)

OANDA is the only broker the project supports. All three parts call OANDA's v20 REST API directly with `requests`; no broker SDK is used.

### 4.1 Get credentials

1. Open an OANDA account. Use a **practice (demo)** account while testing.
2. In the OANDA account portal, open **Manage API Access** and generate a personal access token.
3. Note your **account ID**. Practice account IDs look like `101-001-XXXXXXXX-001`.

### 4.2 Configure `defs.py`

Each part has its own `defs.py`, so update every copy you plan to use:

- [`defs.py`](defs.py) (research)
- [`TradingBotStarter/defs.py`](TradingBotStarter/defs.py) (live bot)
- [`WebDashStarter/defs.py`](WebDashStarter/defs.py) (dashboard)

```python
API_KEY = "<your-api-token>"
ACCOUNT_ID = "<your-account-id>"
OANDA_URL = 'https://api-fxpractice.oanda.com/v3'     # practice

SECURE_HEADER = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json'               # needed only for orders (live bot)
}
```

| Environment | `OANDA_URL` |
|---|---|
| Practice (demo money) | `https://api-fxpractice.oanda.com/v3` |
| Live (real money) | `https://api-fxtrade.oanda.com/v3` |

A token only works with the environment it was created for. A live account also needs a live token.

> **Keep credentials out of git.** The repository has no `.gitignore`, and the `defs.py` files are tracked. A safer pattern is to read the values from environment variables:
>
> ```python
> import os
> API_KEY = os.environ["OANDA_API_KEY"]
> ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
> ```

### 4.3 Test the connection

From the repo root:

```bash
python -c "from oanda_api import OandaAPI; print(OandaAPI().fetch_instruments()[0])"
```

`200` means the token and account ID work. `401` means OANDA rejected the token.

---

## 5. Historical data pipeline

```
instrument.ipynb / OandaAPI().save_instruments()  ──►  instruments.pkl
                                                            │
collect_his_data.py  ◄──────────────────────────────────────┘
        │  M5, H1, H4 for 2020-01-01 to 2022-12-31, 21 pairs
        ▼
his_data/{PAIR}_{GRANULARITY}.pkl  ──►  ma_sim.py, inside_bar_sim.py, notebooks
```

1. **Instrument list.** Run `python -c "from oanda_api import OandaAPI; OandaAPI().save_instruments()"` or the `instrument.ipynb` notebook. This saves `name`, `type`, `displayName`, `pipLocation` and `marginRate` for every instrument on the account.
2. **Candles.** Run `python collect_his_data.py`. OANDA limits how many candles one request returns, so the script walks the date range in windows of 2,000 candles, drops duplicate timestamps, sorts the result and saves one pickle per pair and granularity. The date range is hardcoded in `create_file()`, and the granularities are in `INCREMENTS`.

**The 21 test pairs** come from the currencies `GBP,EUR,USD,CAD,JPY,NZD,CHF`. `Instrument.get_pairs_from_string()` keeps every `A_B` combination that exists in `instruments.pkl`:

`CAD_CHF CAD_JPY CHF_JPY EUR_CAD EUR_CHF EUR_GBP EUR_JPY EUR_NZD EUR_USD GBP_CAD GBP_CHF GBP_JPY GBP_NZD GBP_USD NZD_CAD NZD_CHF NZD_JPY NZD_USD USD_CAD USD_CHF USD_JPY`

### Candle data format

Every candle DataFrame in the project is built by `OandaAPI.candles_to_df()`:

| Column | Type | Meaning |
|---|---|---|
| `time` | tz-aware UTC datetime | Candle **open** time |
| `volume` | int | Tick volume |
| `mid_o`, `mid_h`, `mid_l`, `mid_c` | float | Mid-price open, high, low, close |
| `bid_o` … `bid_c` | float | Bid prices (research and bot only) |
| `ask_o` … `ask_c` | float | Ask prices (research and bot only) |

The candle that is still forming is always dropped. Only completed candles are used.

**Pips:** `Instrument.pipLocation` is stored as a multiplier: OANDA's `-4` becomes `0.0001` and `-2` (JPY pairs) becomes `0.01`. A price difference divided by `pipLocation` gives pips.

---

## 6. Strategies

All signals use the same encoding: `BUY = 1`, `SELL = -1`, `NONE = 0`. The live bot multiplies the signal by the configured `units` to get the signed order size.

### 6.1 Moving-average crossover (backtest: `ma_sim.py`)

**Rule:** compute a short and a long simple moving average of the mid close.
- **BUY** when `MA_short - MA_long` moves from below zero to zero or above.
- **SELL** when it moves from above zero to zero or below.

**Trade model:** always in the market. Each crossover closes the previous position and opens the opposite one. The gain of a trade is the mid-close move from its crossover to the next one, in pips, multiplied by the direction. Spread is not included.

**Parameter grid** (H1 data, 21 pairs):

```python
ma_short = [4, 8, 16, 24, 32, 64]
ma_long  = [8, 16, 32, 64, 96, 128, 256]   # combinations with short >= long are skipped
```

That gives 30 combinations × 21 pairs = 630 tests.

**Run:**

```bash
python ma_sim.py      # writes ma_test_res.pkl, all_trades.pkl and ma_results.xlsx
python ma_excel.py    # rebuilds ma_results.xlsx from the two pickles
```

- `ma_test_res.pkl` has one row per pair and combination: `pair, num_trades, total_gain, mean_gain, min_gain, max_gain, mashort, malong`.
- `all_trades.pkl` holds every simulated trade with `GAIN`, in pips, and `DURATION`, in hours.
- `ma_results.xlsx` has one sheet per pair, sorted by total gain, with a cumulative-gain line chart for that pair's best crossover.

**Recorded results** (from `ma_sim_explorer.ipynb`; that run used an earlier, shorter H1 data set starting June 2022, not the current 2020–2022 files):

| Crossover | Trades | Total gain over 21 pairs | Pairs with a profit |
|---|---|---|---|
| MA_32_64 | 1,439 | −1,021.1 pips | 11 / 21 (52%) |
| MA_8_96 | 1,561 | −3,749.1 pips | 9 / 21 (43%) |
| MA_64_96 | 991 | −4,799.1 pips | 7 / 21 (33%) |
| MA_16_96 | 1,205 | −5,054.6 pips | 9 / 21 (43%) |
| MA_24_96 | 1,056 | −5,637.4 pips | 10 / 21 (48%) |

These were the five best of the 30 combinations, and every combination lost money in total. Across all 66,885 simulated trades, the average trade lost 4.05 pips before spread. Results vary a lot by pair. For example, `candle_plot.ipynb` shows EUR_USD 16/64 on 2020–2022 H1 data at +1,482.8 pips over 372 trades.

### 6.2 Inside-bar momentum (backtest: `inside_bar_sim.py`)

An **inside bar** is a candle whose high and low both fall inside the previous candle's range (the "mother bar"). The strategy expects a breakout in the direction of the mother bar.

| Step | Rule (H4 candles) |
|---|---|
| Signal | `high < previous high` **and** `low > previous low`. The direction is the mother bar's direction: BUY if its close > open, otherwise SELL |
| Entry (stop order) | BUY at `mother ask high + 10% of mother range`; SELL at `mother bid low − 10% of mother range` |
| Stop loss | 40% of the mother range beyond the entry (`SLOSS = 0.4`) |
| Take profit | 80% of the mother range from the entry (`TPROFIT = 0.8`), so reward:risk is 2:1 |
| Trade window | From the close of the inside bar until the close of the next signal candle |

**Evaluation:** for each signal, the M5 candles in the trade window are replayed.
- A BUY is triggered when the M5 **ask** close goes above the entry. From then on, the **bid** close is checked against TP and SL. A SELL works the other way round.
- Results are in **R** (multiples of the stop distance): TP = **+2**, SL = **−1**.
- If neither level is hit, the trade is valued at its distance from entry at the end of the window, as a fraction of R.
- A signal whose entry is never triggered scores 0.

**Run:**

```bash
python inside_bar_sim.py    # prints the total R per pair and a grand total for all 21 pairs
```

**Recorded notebook results** (USD_JPY, H4, 2020–2022):

| Notebook | Method | Result |
|---|---|---|
| `inside_bar_explore.ipynb` | Checked on H4 closes, mid prices | 747 trades, +603 R |
| `inside_bar_explore_spread.ipynb` | Checked on H4 closes, entries from bid/ask | 746 trades, +583 R |
| `inside_bar_timings_spread.ipynb` | M5 replay with bid/ask (same as the script) | **+79.2 R** |
| `inside_bar_timings.ipynb` | M5 replay with mid prices | 795 R. **Not valid**: the TP and SL comparisons in that notebook are inverted |

The M5 bid/ask replay is the most realistic of these. The H4-close versions only see candle closes and let trades overlap.

### 6.3 Live MA crossover (`TradingBotStarter/technicals.py`)

This is the same crossover idea as 6.1, run live on **M1** candles for each pair in `settings.json`. The default settings use a 2/8 crossover with 1,000 units, a combination not covered by the backtest grid. One detail differs from the backtest: the live check uses strict inequalities (`D_PREV > 0 and D_NOW < 0` → SELL, and the reverse → BUY). [Section 7](#7-live-trading-bot) describes the full loop.

### 6.4 Dashboard indicators and candle patterns (`WebDashStarter/data_prep.py`)

These are signals to look at on the dashboard; nothing trades on them automatically. They are computed on the last 100 completed **M1** mid-price candles of each pair, and only the latest candle is shown.

| Column | Calculation | Values |
|---|---|---|
| `MACD_CROSS` | MACD = EMA12 − EMA26; signal = EMA9 of MACD; histogram = MACD − signal | `1` when the histogram crosses up through 0, `-1` when it crosses down, else `0` |
| `BB_SIGNAL` | Typical price (H+L+C)/3; 20-period SMA ± 2 standard deviations | `1` when a bullish candle closes above the upper band **or** a bearish candle closes below the lower band (see [known issues](#11-known-issues-and-limitations)) |
| `TREND` | EMA 8, 20 and 50 of the close | `1` if EMA8 > EMA20 > EMA50, `-1` if EMA8 < EMA20 < EMA50, else `0` |
| `DIRECTION` | close vs open | `1` bullish (close ≥ open), `-1` bearish |
| `BODY_PERC` | \|close − open\| ÷ (high − low) | 0–1 |

**Candle patterns** use these measurements: body size as a fraction of the candle range, and the top and bottom wicks as fractions of the range. Thresholds are constants at the top of `data_prep.py`.

| Pattern | Rule |
|---|---|
| `HAMMER` | Body < 20% of range, and the top **or** bottom wick < 15% of range (catches hammers and inverted hammers / shooting stars) |
| `DOJI` | Body < 5% of range |
| `MARUBOZU` | Body > 95% of range |
| `SPINNING_TOP` | Body < 20% of range, and top wick between 45% and 55% of range (body near the centre) |
| `ENGULFING` | Direction differs from the previous candle, both bodies > 60% of their ranges, and this body > 1.1 × the previous body |

---

## 7. Live trading bot

### How it works

```
bot.py  TradingBot.run()   (repeats every 10 s)
  │
  ├─ update_timings()      for each pair: ask OANDA for the last complete M1 candle;
  │                        if it is newer than Timing.last_candle, mark the pair ready
  │
  ├─ process_pairs()       for each ready pair:
  │     Technicals.get_trade_decision(candle_time)
  │        ├─ fetch the last (long_ma + 2) candles; skip if the newest candle time
  │        │  doesn't match the expected one
  │        └─ compute MA_short, MA_long, D_PREV, D_NOW → BUY / SELL / NONE
  │     units = decision × settings[pair].units
  │
  └─ TradeManager.place_trades(trades)
        ├─ close_trades(): close every open trade on those pairs (GET openTrades → PUT close)
        └─ create_trades(): open a market order for each (POST orders, FOK)
```

So the bot reverses its position on every crossover. A new signal closes the existing trade on that pair and opens one in the signal's direction.

### Configuration

[`TradingBotStarter/settings.json`](TradingBotStarter/settings.json) has one entry per pair to trade:

```json
{
    "EUR_USD": { "pair": "EUR_USD", "units": 1000, "short_ma": 2, "long_ma": 8 }
}
```

| Field | Meaning |
|---|---|
| `pair` | OANDA instrument name |
| `units` | Order size in base-currency units (1,000 = one micro lot). Always positive; the signal sets the direction |
| `short_ma`, `long_ma` | Moving-average periods in candles. Currently capped at `long_ma = 8`; see [known issues](#11-known-issues-and-limitations) |

The timeframe and polling interval are constants at the top of `bot.py`: `GRANULARITY = "M1"` and `SLEEP = 10.0`.

### Running

```bash
cd TradingBotStarter
python bot.py           # start the bot (Ctrl+C to stop)
python settings.py      # print the loaded settings
python oanda_api.py     # print the account's open trades
python runner.py        # manual console: T = buy 1000 EUR_USD, C = close it, Q = quit
```

### Logs

The bot writes to `TradingBotStarter/logs/`. Each run overwrites the files.

| File | Contents |
|---|---|
| `Bot.log` | Startup settings, new-candle detection, which pairs are ready |
| `Technicals.log` | The last two rows of the computed MA table for each decision, and the decision |
| `Trade.log` | Each close and open request and its result |

`TradingBot.log`, `TechnicalsBot.log` and `Test.log` in that folder are left over from earlier versions.

---

## 8. Web dashboard

### Running

The dashboard needs two processes, both started in `WebDashStarter/`:

```bash
# terminal 1: refresh data.json now and then every minute
python run_tasks.py

# terminal 2: web server (reads FLASK_APP and FLASK_DEBUG from .env)
flask run               # or: python app.py
```

Then open http://127.0.0.1:5000.

### How it works

- `run_tasks.py` calls `data_prep.save_file()` straight away and then once a minute. Each call fetches candles for the 21 pairs in `PAIRS`, computes the indicators from [section 6.4](#64-dashboard-indicators-and-candle-patterns-webdashstarterdata_preppy), and writes the latest row per pair to `data.json`.
- `app.py` uses WhiteNoise to serve `static/`, so `/` opens `index.html`. It also serves the two JSON endpoints below.
- `static/app.js` is a Vue 2 app, loaded from CDN with no build step:
  - It polls `/kpi_data` every 15 seconds and shows the KPI table. Cells turn green for `1` and red for `-1`.
  - Clicking a row loads `/price_data/<pair>` and draws a Plotly candlestick chart of the last 50 M5 candles.
  - **Home** returns to the table.

---

## 9. API reference

### 9.1 OANDA REST endpoints used

All paths are relative to `OANDA_URL`, and every request sends `Authorization: Bearer <API_KEY>`.

| Method | Path | Used by | Purpose |
|---|---|---|---|
| GET | `/accounts/{ACCOUNT_ID}/instruments` | all | List tradeable instruments (name, pipLocation, marginRate…) |
| GET | `/instruments/{pair}/candles` | all | Candles. Params: `granularity` (`M1`, `M5`, `H1`, `H4`…), `price` (`M`, `B`, `A` or a combination such as `MBA`), and either `count` or `from`/`to` (Unix seconds) |
| POST | `/accounts/{ACCOUNT_ID}/orders` | bot | Market order, plus optional `TAKE_PROFIT` / `STOP_LOSS` orders linked by `tradeID` |
| PUT | `/accounts/{ACCOUNT_ID}/trades/{tradeID}/close` | bot | Close a trade |
| GET | `/accounts/{ACCOUNT_ID}/openTrades` | bot | List open trades |

Market order body sent by `place_trade()` (negative `units` sell):

```json
{ "order": { "units": 1000, "instrument": "EUR_USD", "timeInForce": "FOK",
             "type": "MARKET", "positionFill": "DEFAULT" } }
```

Take-profit / stop-loss body sent by `set_sl_tp()`:

```json
{ "order": { "timeInForce": "GTC", "price": "1.10500", "type": "TAKE_PROFIT", "tradeID": "261" } }
```

### 9.2 Python client classes

**Research: [`oanda_api.py`](oanda_api.py)**

| Method | Returns |
|---|---|
| `fetch_instruments()` | `(status_code, json)` |
| `get_instruments_df()` | DataFrame `[name, type, displayName, pipLocation, marginRate]` or `None` |
| `save_instruments()` | Writes `instruments.pkl` |
| `fetch_candles(pair, count=None, granularity="H1", date_from=None, date_to=None, as_df=False)` | `(status_code, json or DataFrame)`. `date_from`/`date_to` take priority over `count`; the default is 300 candles |
| `OandaAPI.candles_to_df(candles_json)` | Candle DataFrame ([format](#candle-data-format)) |

**Research helpers:** [`instrument.py`](instrument.py) and [`utils.py`](utils.py)

| Function | Purpose |
|---|---|
| `Instrument.get_instruments_dict()` | `{ "EUR_USD": Instrument, ... }` with `.pipLocation`, `.marginRate`, … |
| `Instrument.get_instrument_by_name(pair)` | One `Instrument` or `None` |
| `Instrument.get_pairs_from_string("GBP,EUR,...")` | All existing pairs built from those currencies |
| `utils.get_his_data_filename(pair, granularity)` | `his_data/{pair}_{granularity}.pkl` |
| `utils.get_utc_dt_from_string(s)` / `utils.time_utc()` | UTC datetimes |

**Live bot: [`TradingBotStarter/oanda_api.py`](TradingBotStarter/oanda_api.py)**

| Method | Returns |
|---|---|
| `make_request(url, params, added_headers, verb, data, code_ok)` | `(status_code, json or None)`; `(400, None)` on a connection error |
| `fetch_candles(pair, count=10, granularity="H1")` | `(status_code, DataFrame or None)` |
| `last_complete_candle(pair, granularity="H1")` | Time of the newest complete candle, or `None` |
| `place_trade(pair, units, take_profit=None, stop_loss=None)` | `(trade_id, ok)` on success, `None` on failure |
| `set_sl_tp(price, order_type, trade_id)` | `True` / `False` |
| `close_trade(trade_id)` | `True` / `False` |
| `open_trades()` | `([OandaTrade], ok)`. `OandaTrade` has `trade_id`, `instrument`, `currentUnits`, `unrealizedPL`, `openTime` |

**Dashboard: [`WebDashStarter/oanda_api.py`](WebDashStarter/oanda_api.py)**

| Method | Returns |
|---|---|
| `fetch_candles(pair, count=100, granularity="H1")` | `(status_code, DataFrame)` with mid prices only |
| `OandaAPI.pricing_api(pair, count=50, granularity="M5")` | `{time: [...], volume: [...], mid_o: [...], ...}` lists ready for Plotly, or `[]` |
| `get_pairs_list()` | Raw instrument list or `None` |

### 9.3 Dashboard HTTP API

| Endpoint | Response |
|---|---|
| `GET /` | The dashboard page (`static/index.html`) |
| `GET /kpi_data` | Contents of `data.json`: `{ "price_data": [ {PAIR, time, volume, mid_o, mid_h, mid_l, mid_c, MACD_CROSS, BB_SIGNAL, BODY_PERC, DIRECTION, HAMMER, DOJI, MARUBOZU, SPINNING_TOP, ENGULFING, TREND}, ... ], "updated": "YYYY-MM-DD HH:MM:SS" }` (UTC) |
| `GET /price_data/<pair>` | Last 50 M5 candles as column lists: `{ "time": ["MM-DD HH:MM", ...], "volume": [...], "mid_o": [...], "mid_h": [...], "mid_l": [...], "mid_c": [...] }` |

---

## 10. Extending the project

### 10.1 Add a new strategy to the backtester

A backtest has three steps: **load candles → add a `SIGNAL` column → score the signals.** Two scoring models already exist:

- **Signal-to-signal, in pips** (like `ma_sim.py`): hold each signal until the next one. Use this for always-in-market strategies.
- **Entry, stop loss and take profit replayed on M5, in R** (like `inside_bar_sim.py`): build a DataFrame with `SIGNAL`, `ENTRY`, `STOPLOSS`, `TAKEPROFIT`, `trade_start` and `trade_end`, then pass it with the pair's M5 data to `inside_bar_sim.evaluate_pair(df_trades, m5_data)`. A take-profit hit scores `TPROFIT / SLOSS` from that module (2.0), so either keep a 2:1 reward:risk or change those constants.

Example: a new file `rsi_sim.py` at the repo root using the first model:

```python
import pandas as pd

import utils
from instrument import Instrument

BUY, SELL, NONE = 1, -1, 0
CURRENCIES = "GBP,EUR,USD,CAD,JPY,NZD,CHF"

def add_signal(df, period=14, low=30, high=70):
    delta = df.mid_c.diff()
    avg_gain = delta.clip(lower=0).rolling(period).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(period).mean()
    df['RSI'] = 100 - 100 / (1 + avg_gain / avg_loss)
    rsi_prev = df.RSI.shift(1)
    df['SIGNAL'] = NONE
    df.loc[(rsi_prev < low) & (df.RSI >= low), 'SIGNAL'] = BUY
    df.loc[(rsi_prev > high) & (df.RSI <= high), 'SIGNAL'] = SELL
    return df

def evaluate(df, pip):
    # hold each signal until the next one, as ma_sim.py does
    trades = df[df.SIGNAL != NONE].copy()
    trades['GAIN'] = (trades.mid_c.diff().shift(-1) / pip) * trades.SIGNAL
    return trades.dropna(subset=['GAIN'])

def run(granularity="H1"):
    instruments = Instrument.get_instruments_dict()
    total = 0
    for pair in Instrument.get_pairs_from_string(CURRENCIES):
        df = pd.read_pickle(utils.get_his_data_filename(pair, granularity))
        trades = evaluate(add_signal(df), instruments[pair].pipLocation)
        total += trades.GAIN.sum()
        print(f"{pair} trades:{trades.shape[0]} gain:{trades.GAIN.sum():.1f} pips")
    print(f"TOTAL {total:.1f} pips")

if __name__ == "__main__":
    run()
```

Tips:
- To include spread, compute gains from `ask_c` when buying and `bid_c` when selling, as `inside_bar_sim.py` does.
- To test a parameter grid, loop over the parameters and collect results into a DataFrame, as `ma_sim.run()` does. You can reuse `ma_excel.create_excel()` if your result columns match.

### 10.2 Add a strategy to the live bot

The bot only needs a class with `get_trade_decision(candle_time)` that returns `BUY`, `SELL` or `NONE`. The easiest route is to subclass `Technicals`, which already fetches candles and checks that the newest candle matches.

**Step 1: lift the 10-candle limit.** In `TradingBotStarter/oanda_api.py`, `fetch_candles()` ignores its `count` argument. Fix it:

```python
params['count'] = count        # was: params['count'] = 10
```

**Step 2: add the strategy class**, for example `TradingBotStarter/rsi_technicals.py`:

```python
from technicals import Technicals
from defs import BUY, SELL, NONE

class RsiTechnicals(Technicals):

    def get_trade_decision(self, candle_time):
        # +3: RSI needs period+1 rows for its first value, one more for the previous
        # value, and OANDA's still-forming candle is dropped from the response
        df = self.fetch_candles(self.settings.rsi_period + 3, candle_time)
        if df is None:
            return NONE
        return self.process_candles(df)

    def process_candles(self, df):
        period = self.settings.rsi_period
        delta = df.mid_c.diff()
        avg_gain = delta.clip(lower=0).rolling(period).mean()
        avg_loss = (-delta.clip(upper=0)).rolling(period).mean()
        df['RSI'] = 100 - 100 / (1 + avg_gain / avg_loss)

        prev, now = df.RSI.iloc[-2], df.RSI.iloc[-1]
        decision = NONE
        if prev < 30 <= now:
            decision = BUY
        elif prev > 70 >= now:
            decision = SELL

        self.log_message(f"{self.pair} RSI prev:{prev:.1f} now:{now:.1f} decision:{decision}")
        return decision
```

**Step 3: add the new parameter to the settings.** In `settings.py`:

```python
class Settings():
    def __init__(self, pair, units, short_ma, long_ma, rsi_period=14):
        self.pair = pair
        self.units = units
        self.short_ma = short_ma
        self.long_ma = long_ma
        self.rsi_period = rsi_period

    @classmethod
    def from_file_ob(cls, ob):
        return Settings(ob['pair'], ob['units'], ob['short_ma'], ob['long_ma'],
                        ob.get('rsi_period', 14))
```

and in `settings.json`:

```json
"EUR_USD": { "pair": "EUR_USD", "units": 1000, "short_ma": 2, "long_ma": 8, "rsi_period": 14 }
```

**Step 4: switch the bot to the new class.** In `bot.py`:

```python
from rsi_technicals import RsiTechnicals
...
techs = RsiTechnicals(self.settings[pair], self.api, pair, GRANULARITY, log=self.tech_log)
```

To trade a different timeframe, change `GRANULARITY` in `bot.py` (for example `"M5"` or `"H1"`).

### 10.3 Add stop loss and take profit to live trades

`OandaAPI.place_trade()` already accepts `take_profit` and `stop_loss` prices, but `TradeManager` never passes them. To use them:

1. Have your strategy return the prices along with the signal, and add them to each trade dict in `bot.process_pairs()`, for example `{'pair': pair, 'units': units, 'take_profit': tp, 'stop_loss': sl}`.
2. In `TradeManager.create_trades()`, call `self.api.place_trade(t['pair'], t['units'], t.get('take_profit'), t.get('stop_loss'))`.
3. Round prices to the instrument's `displayPrecision` from the instruments endpoint. OANDA rejects prices with too many decimals.

### 10.4 Add or remove traded pairs

- **Live bot:** add or remove entries in `TradingBotStarter/settings.json`. The bot trades every key in that file.
- **Dashboard:** edit the `PAIRS` list in `WebDashStarter/data_prep.py`.
- **Backtests:** change the currency string (`"GBP,EUR,USD,CAD,JPY,NZD,CHF"`) in `collect_his_data.py`, `ma_sim.py` and `inside_bar_sim.py`, then collect data for the new pairs.

### 10.5 Add an indicator to the dashboard

1. In `data_prep.py`, write a function that adds a column to the DataFrame, and call it in `get_pair_data()`.
2. Add the column name to `DF_COLS`.
3. In `static/index.html`, add a `<th>` header and a matching `<td>`. Use `{{ item.YOUR_COL }}` for a value, or `:class="applyDirectionClass(item.YOUR_COL)"` for a red/green cell based on `-1`/`1`.

The indicator only sees the last 100 M1 candles, and rows with missing values are dropped. Long look-back periods therefore leave few rows; the 50-period EMA already uses half the window.

### 10.6 Connect a different broker

No other broker is implemented, but the live bot only depends on a small set of methods on `self.api`. Write an adapter class with the same interface and swap it in at `bot.py` (`self.api = OandaAPI()`):

```python
class MyBrokerAPI():

    def fetch_candles(self, pair_name, count=10, granularity="H1"):
        """Return (status_code, DataFrame). The DataFrame has complete candles only,
        with columns time (tz-aware UTC), volume, mid_o..mid_c, bid_o..bid_c, ask_o..ask_c."""

    def last_complete_candle(self, pair_name, granularity="H1"):
        """Return the time of the newest complete candle, or None."""

    def place_trade(self, pair, units, take_profit=None, stop_loss=None):
        """units > 0 buys, units < 0 sells. Return (trade_id, ok)."""

    def close_trade(self, trade_id):
        """Return True if the trade was closed."""

    def open_trades(self):
        """Return (list of objects with .trade_id and .instrument, ok)."""
```

Inside the adapter, translate:
- **pair names** from OANDA style (`EUR_USD`) to the broker's symbols (for example `EURUSD`)
- **granularity codes** (`M1`, `M5`, `H1`, `H4`)
- **order size**: OANDA uses units of base currency, many brokers use lots

For the research scripts, only the data source needs replacing. Anything that writes pickles in the [candle data format](#candle-data-format) to `his_data/{PAIR}_{GRANULARITY}.pkl` works with `ma_sim.py`, `inside_bar_sim.py` and the notebooks.

---

## 11. Known issues and limitations

**Live bot (`TradingBotStarter/`)**
- `fetch_candles()` always requests 10 candles, so `long_ma` can be at most 8. With a larger value the long MA is never complete and the bot never trades. See the fix in [10.2](#102-add-a-strategy-to-the-live-bot).
- `place_trade()` returns `(trade_id, ok)` on success but `None` on failure:
  - `TradeManager.create_trades()` treats the result as a plain ID, which is why the logs show `Opened (261, True)`.
  - `runner.py` crashes when an order fails, because it unpacks the `None`.
- If a candle request fails during the loop, `last_complete_candle()` returns `None` and the comparison in `update_timings()` raises an exception, which stops the bot.
- `make_request()` writes any `added_headers` into the shared `defs.SECURE_HEADER` dict, which changes them for every later request.
- No risk management: no stop loss, take profit, position sizing or daily loss limit. A new signal on a pair closes any open trade on that pair, even one in the same direction.

**Research scripts**
- `ma_sim.py`, `candle_plot.ipynb` and `inside_bar_timings*.ipynb` were written when `his_data/` stored `time` as text, and they call `dateutil.parse()` on it. The current files (collected after lesson #45) store real datetimes, so these steps fail. Replace `[parse(x) for x in df.time]` with `pd.to_datetime(df.time, utc=True)`, which handles both formats.
- `ma_excel.py` needs pandas < 2 (`ExcelWriter.save()` was removed in 2.0; newer pandas uses `writer.close()`).
- `inside_bar_timings.ipynb` (mid-price version) has inverted take-profit and stop-loss comparisons, so its total is not meaningful. The `_spread` version and `inside_bar_sim.py` are correct.
- `python instrument.py` calls a method that doesn't exist (`get_test_pairs`). Use `Instrument.get_pairs_from_string()` instead.

**Dashboard**
- `BB_SIGNAL` returns `1` both above the upper band and below the lower band. The prototype in `candle_indicators.ipynb` returned `-1` for a close above the upper band.
- The candle-pattern columns are `true`/`false`, but `index.html` colours cells with `applyDirectionClass()`, which only reacts to `1`/`-1`, so pattern cells are never highlighted. `app.js` already has an `applyOnOffClass()` method for boolean values.
- `run_tasks.py` loops without sleeping and keeps one CPU core busy. Adding `time.sleep(1)` inside the loop fixes this.
- If the candle request for any pair fails, `get_pair_data()` raises an exception and the refresh stops.

**Repository**
- There is no `.gitignore`, so `venv/`, `__pycache__/`, logs, data pickles and `defs.py` credentials are all committed.
- The committed `venv/` folders were built on another machine and must be recreated ([section 3](#3-setup)).
- There are no automated tests.
