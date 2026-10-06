import pandas as pd


def sma(series, period):
    return series.rolling(window=period).mean()


def atr(df, period=14):
    """Average True Range: simple moving average of the true range of mid prices."""
    prev_close = df.mid_c.shift(1)
    true_range = pd.concat([
        df.mid_h - df.mid_l,
        (df.mid_h - prev_close).abs(),
        (df.mid_l - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()
