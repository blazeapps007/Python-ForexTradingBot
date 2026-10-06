# Python Forex Trading Bot

This project uses several tools to build an automated trading strategy. It backtests strategies on real historical Forex data, monitors the market through a live indicator dashboard, and runs a bot that trades automatically:
- Forex through **OANDA**;
- crypto and **bStocks** (Binance's tokenized US stocks) through **Binance spot**;
- crypto perpetuals through **Binance USDⓈ-M futures**.

Every bot trade carries a stop loss and a take profit, and its size is set by the share of the balance you're willing to risk.

> **Warning:** the bot runs in **paper mode** by default, which simulates orders on live prices. With `TRADING_MODE=broker` it sends real orders to the environments set in `.env`. Use OANDA practice and Binance testnet accounts. Live accounts are refused unless `ALLOW_REAL_MONEY=yes` is set.

---

## Contents

1. [Project overview](#1-project-overview)
2. [Repository layout](#2-repository-layout)
3. [Setup](#3-setup)
4. [Connecting brokers](#4-connecting-brokers)
5. [Historical data pipeline](#5-historical-data-pipeline)
6. [Strategies](#6-strategies)
7. [Trading bot](#7-trading-bot)
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
| **Trading bot** | [`TradingBotStarter/`](TradingBotStarter/) | Trades strategy signals on OANDA, Binance spot and Binance futures with ATR-based stop loss and take profit and risk-% sizing; runs in Docker, paper mode by default |
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
├── docker-compose.yml       # services: bot (paper by default) and tests
├── .env.example             # copy to .env: trading mode, broker environments, API keys
│
├── TradingBotStarter/
│   ├── bot.py               # TradingBot main loop (entry point)
│   ├── settings.json        # instruments, strategy parameters, risk settings
│   ├── config.py            # loads settings.json + environment variables, real-money guard
│   ├── trade_manager.py     # one position per instrument: hold, reverse or exit on signals
│   ├── risk.py              # ATR stop loss / take profit, risk-% sizing, order guardrails
│   ├── indicators.py        # SMA, ATR
│   ├── strategies/          # Strategy interface + ma_cross (add new strategies here)
│   ├── brokers/             # Broker interface + oanda, binance_spot, binance_futures, paper, factory
│   ├── tests/               # pytest unit tests + network integration tests
│   ├── Dockerfile, requirements.txt, requirements-dev.txt, pytest.ini
│   └── logs/                # trading_bot.log, paper_state.json, paper_trades.csv (git-ignored)
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

### Trading bot: Docker

The bot is built, tested and run **only in Docker**. You need Docker Desktop with Compose; no local Python is required.

```bash
cp .env.example .env                       # then fill in keys (optional for paper mode)
docker compose build                       # build the image
docker compose run --rm tests              # unit tests (offline)
docker compose run --rm tests pytest -m integration   # network tests against broker test environments
docker compose up bot                      # run the bot (Ctrl+C to stop); paper mode by default
docker compose logs -f bot                 # follow the log when started with `up -d`
```

The tests service mounts `TradingBotStarter/` into the container, so code edits are picked up without rebuilding. The bot service uses the built image, so run `docker compose build` after changing the code.

### Research and dashboard: local Python

**Requirements:** Python 3.11 and an OANDA account (a free practice account works; see [section 4](#4-connecting-brokers)).

The `venv/` folders in the repository were created on another computer and won't work on yours. Create a fresh environment instead. One environment at the repo root can serve the research scripts and the dashboard:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install "pandas<2" "numpy<2" requests python-dateutil plotly xlsxwriter jupyter flask python-dotenv whitenoise schedule
```

`pandas<2` is needed because `ma_excel.py` calls `ExcelWriter.save()`, which pandas 2.0 removed. If you only want the dashboard, `WebDashStarter/requirements.txt` lists its own dependencies. The trading bot doesn't need this environment; it runs in Docker.

**Every script uses paths relative to the folder it runs in** (`his_data/`, `settings.json`, `logs/`, `data.json`), so always `cd` into a project's folder before running its scripts.

---

## 4. Connecting brokers

| Broker | Markets | Used by | Library |
|---|---|---|---|
| OANDA | Forex | research, dashboard, bot | OANDA v20 REST API via `requests` |
| Binance spot | Crypto pairs and **bStocks** (tokenized US stocks such as `TSLAB/USDT`, `NVDAB/USDT`) | bot | [ccxt](https://github.com/ccxt/ccxt) |
| Binance USDⓈ-M futures | Crypto perpetuals (`ETH/USDT:USDT`), long and short | bot | ccxt |

### 4.1 OANDA credentials

1. Open an OANDA account. Use a **practice (demo)** account while testing.
2. In the OANDA account portal, open **Manage API Access** and generate a personal access token.
3. Note your **account ID**. Practice account IDs look like `101-001-XXXXXXXX-001`.

**For the bot**, put them in `.env` at the repo root (copied from `.env.example`). `.env` is git-ignored.

```bash
OANDA_API_KEY=<your-api-token>
OANDA_ACCOUNT_ID=<your-account-id>
OANDA_ENV=practice        # or live (real money; also needs ALLOW_REAL_MONEY=yes)
```

In paper mode the bot still needs these keys to read OANDA prices. Without them, OANDA instruments are skipped with a warning.

### 4.2 Binance credentials

| `BINANCE_ENV` | Where to get keys | Notes |
|---|---|---|
| `testnet` (default) | Spot: [testnet.binance.vision](https://testnet.binance.vision) (log in with GitHub, "Generate HMAC_SHA256 Key"). Futures: [testnet.binancefuture.com](https://testnet.binancefuture.com) | Test funds; spot testnet also lists bStocks such as `TSLAB/USDT` |
| `demo` | Binance Demo Trading API management (demo.binance.com) | One key set covers spot and futures |
| `live` | Binance account API management | Real money; needs `ALLOW_REAL_MONEY=yes` |

```bash
BINANCE_API_KEY=<spot key>
BINANCE_API_SECRET=<spot secret>
BINANCE_ENV=testnet
BINANCE_FUTURES_API_KEY=<futures key>        # optional; defaults to BINANCE_API_KEY
BINANCE_FUTURES_API_SECRET=<futures secret>  # optional; defaults to BINANCE_API_SECRET
```

The spot testnet and futures testnet issue separate keys, so set both pairs when testing both markets. With `demo` or `live`, one key pair usually covers both, and the futures variables can stay empty.

Paper mode needs **no Binance keys**: prices come from Binance's public data mirror `data-api.binance.vision`, and futures are simulated on the matching spot price.

**Access notes:**
- bStocks are only offered to eligible users in permitted jurisdictions and are not available to US users. Check your account's eligibility before trading them live.
- Some networks block `binance.com`. The testnet and `binance.vision` hosts may still be reachable, and the bot defaults to those.

### 4.3 Research and dashboard: `defs.py`

The research scripts and dashboard still read OANDA credentials from their own `defs.py`. Update each copy you use:

- [`defs.py`](defs.py) (research)
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

> **Keep credentials out of git.** These two `defs.py` files are tracked by git. A safer pattern is to read the values from environment variables, as the bot does:
>
> ```python
> import os
> API_KEY = os.environ["OANDA_API_KEY"]
> ACCOUNT_ID = os.environ["OANDA_ACCOUNT_ID"]
> ```

### 4.4 Test the connections

```bash
docker compose run --rm tests pytest -m integration -rs
```

- Without keys, two tests run: live prices from the Binance data mirror, and the shape of the futures SL/TP orders against the futures testnet.
- With keys in `.env`, the tests also open and close one minimum-size trade with SL/TP on the OANDA practice account, the Binance spot testnet and the Binance futures testnet.
- `-rs` lists the skipped tests and the reason each was skipped.

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

### 6.3 Live MA crossover (`TradingBotStarter/strategies/ma_cross.py`)

This is the same crossover idea as 6.1, run by the bot on every instrument in `settings.json`. The default is an 8/21 crossover on M5 candles. One detail differs from the backtest: the live check uses strict inequalities (`D_PREV > 0 and D_NOW < 0` → SELL, and the reverse → BUY). The bot adds the stop loss, take profit and size to each signal; [section 7](#7-trading-bot) describes how.

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

## 7. Trading bot

### How it works

```
bot.py  TradingBot.run()            every poll_seconds (10 s), for each instrument:
  │
  ├─ broker.last_complete_candle_time()   new candle since last time? if not, wait
  ├─ broker.reconcile()                   tidy up after SL/TP exits (paper mode checks SL/TP here)
  ├─ broker.get_candles()                 enough complete candles for the strategy and ATR
  │
  └─ TradeManager.process()
        ├─ strategy.decide(candles, position)  →  Decision(BUY / SELL / NONE, optional SL/TP, reason)
        ├─ same direction as the open position →  hold
        ├─ opposite direction                  →  close the position, then:
        │     spot SELL                        →  exit only (spot can't short)
        ├─ risk.build_order()                  →  SL/TP, size, rounding, guardrails (may reject)
        └─ broker.open_position(order)         →  order sent with SL and TP attached
```

There is one position per instrument, and every position has a stop loss and a take profit from the moment it opens.

### Stop loss, take profit and sizing (`risk.py`)

| Step | Rule (defaults) |
|---|---|
| Entry estimate | Ask for a buy, bid for a sell |
| Stop loss | `sl_atr_mult × ATR(atr_period)` from entry: 1.5 × ATR(14). A strategy may set its own instead |
| Take profit | `rr ×` the stop distance: 2 × |
| Size | `balance × risk_pct% ÷ (stop distance × quote→account conversion)`: 1% of the balance is lost if the stop is hit |
| Caps | Spot: free quote balance. Futures: free margin × leverage. Then rounded down to the lot step |

**Rejected orders.** Any of these is logged and nothing is sent:
- SL or TP on the wrong side of the entry;
- the stop closer than `min_sl_spreads` (2) × the bid/ask spread;
- size or order value below the broker minimum;
- `max_open_positions` reached;
- `risk_pct` above 5;
- no way to convert the quote currency to the account currency.

**How each broker attaches SL/TP:**

| Broker | Entry | Stop loss / take profit |
|---|---|---|
| OANDA | Market order (FOK) | `stopLossOnFill` / `takeProfitOnFill` in the same order, so the trade is never unprotected |
| Binance spot | Market buy | OCO sell (`POST /api/v3/orderList/oco`): `LIMIT_MAKER` take profit above, `STOP_LOSS` below. Levels are re-anchored to the actual fill price. If the OCO is rejected, the coins are sold back immediately |
| Binance futures | Market buy or sell | Two reduce-only conditional orders (`STOP_MARKET`, `TAKE_PROFIT_MARKET`) via Binance's algo-order endpoint. If either fails, the position is closed |
| Paper | Simulated fill at bid/ask | Checked on each new candle's high/low (bid/ask where available). If both levels are inside one candle, the stop counts as hit first. A gap through the stop fills at the open |

**Exits and orphan orders:**
- Binance futures, at set-up: one-way position mode, isolated margin, and the `leverage` from settings.
- After an SL/TP exit, `reconcile()` cancels the leftover exit order.
- Spot positions are tracked in `logs/binance_spot_state.json`, so coins you already held are never sold by the bot.

### Modes and environments (`.env`)

| Variable | Values | Default |
|---|---|---|
| `TRADING_MODE` | `paper`: simulate on live prices. `broker`: send orders | `paper` |
| `OANDA_ENV` | `practice`, `live` | `practice` |
| `BINANCE_ENV` | `testnet`, `demo`, `live` | `testnet` |
| `ALLOW_REAL_MONEY` | Must be `yes` before any `live` environment is used in broker mode | `no` |

**Paper mode:**
- Starts with `paper.starting_balance` from `settings.json`.
- Keeps its state in `logs/paper_state.json`, so a restart resumes the open positions.
- Appends every closed trade to `logs/paper_trades.csv`.
- Treats all brokers as one account currency (USD and USDT are treated as equal).

### Configuration (`settings.json`)

```json
{
    "poll_seconds": 10,
    "paper": { "starting_balance": 10000 },
    "defaults": {
        "granularity": "M5", "strategy": "ma_cross", "params": { "short_ma": 8, "long_ma": 21 },
        "risk_pct": 1.0, "atr_period": 14, "sl_atr_mult": 1.5, "rr": 2.0,
        "max_open_positions": 5, "min_sl_spreads": 2.0
    },
    "instruments": [
        { "broker": "oanda",           "symbol": "EUR_USD" },
        { "broker": "binance_spot",    "symbol": "BTC/USDT" },
        { "broker": "binance_spot",    "symbol": "TSLAB/USDT" },
        { "broker": "binance_futures", "symbol": "ETH/USDT:USDT", "leverage": 1 }
    ]
}
```

Every key in `defaults` can be overridden per instrument. Set `"enabled": false` to switch an instrument off.

| Field | Meaning |
|---|---|
| `broker` | `oanda`, `binance_spot` or `binance_futures` |
| `symbol` | OANDA: `EUR_USD`. Binance spot: `BTC/USDT`, bStocks `TSLAB/USDT`. Futures: `ETH/USDT:USDT` |
| `granularity` | `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D` |
| `strategy`, `params` | Strategy name from `strategies/__init__.py` and its parameters |
| `leverage` | Futures only, default 1 |

Start with `M5` or slower. On `M1`, quiet markets (bStocks outside US hours, for example) give ATR stops of a few cents, which the spread guard rejects.

### Running

```bash
docker compose up bot            # foreground; Ctrl+C to stop
docker compose up -d bot         # background
docker compose logs -f bot       # follow the log
docker compose down              # stop and remove
```

At start-up the bot logs the mode and environments, then a `watching` line per instrument. It trades from the next completed candle onward. Each decision is logged with its reason, and each order with entry, SL, TP, size and the amount at risk.

### Logs and state

The bot writes these files to `TradingBotStarter/logs/` (git-ignored):

| File | Contents |
|---|---|
| `trading_bot.log` | Everything also printed to the console (rotated at 5 MB) |
| `paper_state.json`, `paper_trades.csv` | Paper balance, open positions and closed-trade history |
| `binance_spot_state.json` | Spot positions opened by the bot, with their OCO order-list IDs |

`Bot.log`, `Technicals.log`, `Trade.log`, `TradingBot.log`, `TechnicalsBot.log` and `Test.log` are left over from the earlier OANDA-only version.

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
| GET | `/accounts/{ACCOUNT_ID}/summary` | bot | Account NAV (risk sizing) and home currency |
| GET | `/accounts/{ACCOUNT_ID}/pricing?instruments=X&includeHomeConversions=true` | bot | Bid/ask and the quote→account currency factor (`homeConversions[].accountLoss`) |
| POST | `/accounts/{ACCOUNT_ID}/orders` | bot | Market order with the stop loss and take profit attached |
| PUT | `/accounts/{ACCOUNT_ID}/trades/{tradeID}/close` | bot | Close a trade |
| GET | `/accounts/{ACCOUNT_ID}/openTrades` | bot | Open trades, with their SL/TP orders |

Market order body sent by `OandaBroker.open_position()`. Negative `units` sell, and prices use the instrument's `displayPrecision`:

```json
{ "order": { "type": "MARKET", "instrument": "EUR_USD", "units": "-1000",
             "timeInForce": "FOK", "positionFill": "DEFAULT",
             "stopLossOnFill":   { "price": "1.10150", "timeInForce": "GTC" },
             "takeProfitOnFill": { "price": "1.09700", "timeInForce": "GTC" } } }
```

### 9.2 Binance endpoints used (through ccxt 4.5.85)

| Environment | Spot | USDⓈ-M futures |
|---|---|---|
| `testnet` | `testnet.binance.vision` | `testnet.binancefuture.com` |
| `demo` | `demo-api.binance.com` | `demo-fapi.binance.com` |
| `live` | `api.binance.com` | `fapi.binance.com` |
| paper prices | `data-api.binance.vision` (public, read-only) | spot price of the same pair |

| Call | ccxt method | Used for |
|---|---|---|
| `GET /api/v3/klines`, `/fapi/v1/klines` | `fetch_ohlcv` | Candles (the one still forming is dropped) |
| `GET /api/v3/depth`, `/fapi/v1/depth` | `fetch_order_book` | Best bid/ask |
| `GET /api/v3/account`, `/fapi/v2/balance` | `fetch_balance` | Free/total USDT for sizing |
| `POST /api/v3/order` | `create_order` | Spot market buy and sell |
| `POST /api/v3/orderList/oco` | `private_post_orderlist_oco` | Spot SL/TP: `aboveType=LIMIT_MAKER`, `belowType=STOP_LOSS` (or `STOP_LOSS_LIMIT` with a 0.2% limit offset when a symbol doesn't allow `STOP_LOSS`) |
| `DELETE /api/v3/orderList` | `private_delete_orderlist` | Cancel the OCO before an exit on signal |
| `POST /fapi/v1/order` | `create_order` | Futures market entry and exit |
| `POST /fapi/v1/algoOrder` | `create_order` with `stopLossPrice` / `takeProfitPrice` + `reduceOnly` | Futures SL/TP (`STOP_MARKET` / `TAKE_PROFIT_MARKET`) |
| `GET /fapi/v1/openAlgoOrders`, `DELETE /fapi/v1/algoOpenOrders` | `fetch_open_orders` / `cancel_all_orders` with `{"trigger": True}` | Find and cancel leftover SL/TP orders |
| `GET /fapi/v2/positionRisk` | `fetch_positions` | Open futures position |
| position mode, margin type, leverage | `set_position_mode`, `set_margin_mode`, `set_leverage` | One-way, isolated, leverage from settings |

### 9.3 Python client classes

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

**Bot brokers: [`TradingBotStarter/brokers/base.py`](TradingBotStarter/brokers/base.py)**

Every broker (`OandaBroker`, `BinanceSpotBroker`, `BinanceFuturesBroker`, `PaperBroker`) implements the same `Broker` interface:

| Method | Returns |
|---|---|
| `get_candles(symbol, granularity, count)` | DataFrame of complete candles: `time`, `volume`, `mid_o/h/l/c`, plus `bid_*`/`ask_*` where available |
| `last_complete_candle_time(symbol, granularity)` | Time of the newest complete candle, or `None` |
| `get_quote(symbol)` | `Quote(bid, ask, quote_to_account)` |
| `get_instrument(symbol)` | `InstrumentInfo(tick_size, step_size, min_size, min_notional, quote_currency)` |
| `get_balance()` | Balance used for sizing |
| `get_position(symbol)` | The bot's `Position(side, size, entry_price, stop_loss, take_profit, id)` or `None`; raises `BrokerError` if it can't tell |
| `open_position(order)` | `OrderResult(ok, position, error)`. The order always includes `stop_loss` and `take_profit` |
| `close_position(symbol)` | `True` / `False` |
| `max_size(symbol, side, entry)` | Largest size the account can fund, or `None` |
| `reconcile(symbol, granularity)` | Cleans up after SL/TP exits |
| `can_short` (attribute) | `False` for Binance spot |

**Bot strategies: [`TradingBotStarter/strategies/base.py`](TradingBotStarter/strategies/base.py)**

| Member | Purpose |
|---|---|
| `Strategy.required_candles()` | How many complete candles `decide()` needs |
| `Strategy.decide(candles, position)` | Returns `Decision(signal, stop_loss=None, take_profit=None, reason="")` |
| `risk.build_order(decision, ...)` | Turns a decision into an `Order` or raises `RiskError` |

**Dashboard: [`WebDashStarter/oanda_api.py`](WebDashStarter/oanda_api.py)**

| Method | Returns |
|---|---|
| `fetch_candles(pair, count=100, granularity="H1")` | `(status_code, DataFrame)` with mid prices only |
| `OandaAPI.pricing_api(pair, count=50, granularity="M5")` | `{time: [...], volume: [...], mid_o: [...], ...}` lists ready for Plotly, or `[]` |
| `get_pairs_list()` | Raw instrument list or `None` |

### 9.4 Dashboard HTTP API

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

### 10.2 Add a strategy to the trading bot

A strategy only decides. It never places orders: every `Decision` goes through `risk.build_order()`, which adds or checks the stop loss and take profit and sizes the trade.

**Step 1: write the class**, for example `TradingBotStarter/strategies/rsi.py`:

```python
from defs import BUY, SELL
from strategies.base import Decision, Strategy


class RsiStrategy(Strategy):
    """BUY when RSI crosses up through `low`, SELL when it crosses down through `high`."""
    name = "rsi"

    def __init__(self, params=None):
        super().__init__(params)
        self.period = int(self.params.get("period", 14))
        self.low = float(self.params.get("low", 30))
        self.high = float(self.params.get("high", 70))

    def required_candles(self):
        return self.period + 2

    def decide(self, candles, position=None):
        delta = candles.mid_c.diff()
        avg_gain = delta.clip(lower=0).rolling(self.period).mean()
        avg_loss = (-delta.clip(upper=0)).rolling(self.period).mean()
        rsi = 100 - 100 / (1 + avg_gain / avg_loss)
        prev, now = rsi.iloc[-2], rsi.iloc[-1]
        if prev < self.low <= now:
            return Decision(BUY, reason=f"RSI crossed up through {self.low} ({now:.1f})")
        if prev > self.high >= now:
            return Decision(SELL, reason=f"RSI crossed down through {self.high} ({now:.1f})")
        return Decision(reason=f"RSI {now:.1f}")
```

**Step 2: register it** in `strategies/__init__.py`:

```python
from strategies.rsi import RsiStrategy

STRATEGIES = {
    MACrossStrategy.name: MACrossStrategy,
    RsiStrategy.name: RsiStrategy,
}
```

**Step 3: use it** in `settings.json`, per instrument or in `defaults`:

```json
{ "broker": "binance_spot", "symbol": "BTC/USDT", "strategy": "rsi", "params": { "period": 14, "low": 30, "high": 70 } }
```

**Step 4: test it.** Add a unit test next to `tests/test_strategy_and_indicators.py`; `tests/helpers.py` has candle builders. Then run `docker compose run --rm tests`, and run the bot in paper mode before broker mode.

What `decide()` receives:
- `candles`: complete candles only, oldest first, with at least `required_candles()` rows (the bot also fetches enough for ATR).
- `position`: the open `Position` or `None`.

Return `Decision(BUY | SELL | NONE, stop_loss=None, take_profit=None, reason="...")`:
- leave `stop_loss` and `take_profit` as `None` to use the ATR rule;
- or set your own prices, for example below the last swing low. `risk.py` still checks they're on the right side and far enough away, and sizes the trade from your stop.

### 10.3 AI strategies (planned: Amazon Bedrock)

An AI-driven strategy is just another `Strategy`. `decide()` would:
1. build a prompt from the recent candles and the open position;
2. call the model with keys from `.env`;
3. parse a structured answer into `Decision(signal, stop_loss, take_profit, reason)`.

Because the decision still passes through `risk.build_order()`, the model can't:
- skip the stop loss or take profit;
- exceed `risk_pct` or `max_open_positions`;
- send orders directly.

Treat any answer that doesn't parse cleanly as `NONE`, and log the model's `reason` with each trade. This is not built yet.

### 10.4 Tune stop loss, take profit and risk

All of these work in `defaults` or per instrument in `settings.json`:

| Setting | Default | Effect |
|---|---|---|
| `risk_pct` | 1.0 | % of balance lost if the stop is hit (max 5) |
| `atr_period` | 14 | ATR look-back in candles |
| `sl_atr_mult` | 1.5 | Stop distance in ATRs |
| `rr` | 2.0 | Take-profit distance as a multiple of the stop distance |
| `max_open_positions` | 5 | No new orders beyond this many open positions across all instruments |
| `min_sl_spreads` | 2.0 | Reject trades whose stop is closer than this many bid/ask spreads |
| `leverage` | 1 | Futures only |

For example, a wider stop with a 3:1 target on one instrument:

```json
{ "broker": "oanda", "symbol": "GBP_JPY", "sl_atr_mult": 2.0, "rr": 3.0, "risk_pct": 0.5 }
```

### 10.5 Add or remove traded instruments

- **Trading bot:** add or remove entries in `instruments` in `TradingBotStarter/settings.json`, or set `"enabled": false`.
  - Binance symbols use ccxt format: `BTC/USDT` for spot, `ETH/USDT:USDT` for USDⓈ-M perpetuals.
  - bStocks are spot pairs ending in `B/USDT`, for example `TSLAB/USDT` or `NVDAB/USDT`.
- **Dashboard:** edit the `PAIRS` list in `WebDashStarter/data_prep.py`.
- **Backtests:** change the currency string (`"GBP,EUR,USD,CAD,JPY,NZD,CHF"`) in `collect_his_data.py`, `ma_sim.py` and `inside_bar_sim.py`, then collect data for the new pairs.

### 10.6 Add an indicator to the dashboard

1. In `data_prep.py`, write a function that adds a column to the DataFrame, and call it in `get_pair_data()`.
2. Add the column name to `DF_COLS`.
3. In `static/index.html`, add a `<th>` header and a matching `<td>`. Use `{{ item.YOUR_COL }}` for a value, or `:class="applyDirectionClass(item.YOUR_COL)"` for a red/green cell based on `-1`/`1`.

The indicator only sees the last 100 M1 candles, and rows with missing values are dropped. Long look-back periods therefore leave few rows; the 50-period EMA already uses half the window.

### 10.7 Add another broker or exchange

1. **Implement `Broker`** (methods in [9.3](#93-python-client-classes)) in `TradingBotStarter/brokers/<name>.py`. For another exchange that ccxt supports, subclass `CcxtBroker` from `brokers/ccxt_common.py`. It already provides candles, quotes and instrument limits, so you only add balance, positions, open/close, and that exchange's way of attaching SL/TP.
2. **Follow the safety rules:**
   - `open_position()` must attach the stop loss and take profit, or undo the entry if it can't;
   - `get_position()` reports only positions the bot opened;
   - raise `BrokerError` when the position state is unknown, so the bot skips that cycle instead of guessing.
3. **Wire it up:**
   - add the name to `BROKERS` in `config.py`, and any credentials to `AppConfig` and `.env.example`;
   - build it in `brokers/factory.py`, for broker mode and as a paper-mode price source.
4. **Test it** with a fake client like `FakeExchange` or `FakeSession` in `tests/helpers.py`, plus an integration test against the exchange's testnet in `tests/test_integration.py`.

For the research scripts, only the data source needs replacing. Anything that writes pickles in the [candle data format](#candle-data-format) to `his_data/{PAIR}_{GRANULARITY}.pkl` works with `ma_sim.py`, `inside_bar_sim.py` and the notebooks.

---

## 11. Known issues and limitations

**Trading bot (`TradingBotStarter/`)**
- Paper mode:
  - checks the stop loss and take profit once per candle, on that candle's high and low;
  - ignores fees and funding;
  - simulates futures on the spot price of the same pair;
  - treats USD and USDT as one account currency.
- Binance sizing needs the pair's quote asset to be the account asset (USDT). Pairs quoted in other assets (for example `ETH/BTC`) are rejected by the risk check.
- Spot positions opened by the bot are remembered in `logs/binance_spot_state.json`. If that file is deleted while a position is open, the bot loses track of it; the OCO exit order on Binance still protects it.
- Futures set-up switches the account to one-way position mode. Binance refuses this while positions or orders are open, and the bot then logs the error and skips that instrument.
- There is no daily loss limit or portfolio-level exposure check beyond `max_open_positions`.
- The round-trip integration tests need practice or testnet keys and are skipped without them. The order flow is otherwise covered by unit tests with fake brokers, and by paper mode on live prices.
- The old OANDA-only modules (`oanda_api.py`, `oanda_trade.py`, `technicals.py`, `settings.py`, `timing.py`, `utils.py`, `runner.py`) are still in the folder but no longer used.

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
- `.gitignore` now excludes `.env`, `__pycache__/` and the bot's `logs/`. Files committed before it existed (`venv/`, `__pycache__/`, old logs, data pickles) are still tracked until they are removed from the index.
- The research and dashboard `defs.py` files still hold an OANDA key in git; move those to environment variables too.
- The committed `venv/` folders were built on another machine and must be recreated ([section 3](#3-setup)).
- Automated tests exist only for the trading bot (`docker compose run --rm tests`). The research scripts and dashboard have none.
