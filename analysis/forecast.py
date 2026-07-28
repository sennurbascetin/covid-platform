# Task 6: Time Series Forecasting.
# Forecasts future daily case counts using Holt-Winters Exponential
# Smoothing (statsmodels), which fits well here because daily COVID
# case counts have a strong weekly reporting cycle (fewer tests
# processed/reported on weekends) layered on top of a slower trend.
#
# Validated with a train/test split: the model is fit on all data
# except the last N_TEST days, then its forecast for those days is
# compared against what actually happened - an honest accuracy
# check instead of just eyeballing the chart.

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from sf_connect import get_connection, fetch_df

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Set to any country name exactly as it appears in JHU_COVID_19 (see
# task2_top10_countries.png or the API's /countries), or leave as
# "GLOBAL" to forecast the worldwide daily total.
COUNTRY = "Turkey"
N_TEST = 30       # last 30 days held out to validate the model
N_FORECAST = 30   # days to forecast beyond the end of the dataset


def load_daily_series(conn, country: str) -> pd.Series:
    if country == "GLOBAL":
        query = """
            SELECT DATE, SUM(CASES) AS CUM_CONFIRMED
            FROM JHU_COVID_19
            WHERE CASE_TYPE = 'Confirmed'
            GROUP BY DATE
            ORDER BY DATE
        """
        df = fetch_df(conn, query)
    else:
        query = """
            SELECT DATE, CASES AS CUM_CONFIRMED
            FROM JHU_COVID_19
            WHERE CASE_TYPE = 'Confirmed' AND COUNTRY_REGION = %(country)s
            ORDER BY DATE
        """
        cur = conn.cursor()
        cur.execute(query, {"country": country})
        df = cur.fetch_pandas_all()
        df["DATE"] = pd.to_datetime(df["DATE"])

    df = df.set_index("DATE").asfreq("D")  # one row per calendar day
    daily_new = df["CUM_CONFIRMED"].diff()

    # Reporting corrections occasionally make "new cases" negative (a
    # country revises an earlier total down). These are data
    # artifacts, not real case decreases, so they're clipped to 0
    # before modeling - otherwise one correction distorts the trend.
    return daily_new.clip(lower=0).fillna(0)


def evaluate(actual, predicted):
    error = actual - predicted
    mae = error.abs().mean()
    rmse = np.sqrt((error ** 2).mean())
    nonzero = actual != 0
    if nonzero.any():
        mape = (error[nonzero].abs() / actual[nonzero]).mean() * 100
    else:
        # every actual value in the window is zero -> MAPE undefined
        mape = float("nan")
    return mae, rmse, mape


def main():
    conn = get_connection()
    try:
        series = load_daily_series(conn, COUNTRY)
    finally:
        conn.close()

# Trailing zeros mean "reporting stopped", not "zero cases":
 # Turkey switched to weekly bulletins in mid-2022 and stopped
# publishing entirely in early 2023, before JHU's own cutoff.
# Trimming them so the model is trained and judged only on the
# period where reporting actually happened.

    last_reported = series[series > 0].index.max()
    series = series.loc[:last_reported] 

    train, test = series.iloc[:-N_TEST], series.iloc[-N_TEST:]

    model = ExponentialSmoothing(
        train, trend="add", seasonal="add", seasonal_periods=7,
        damped_trend=True,
    ).fit()

    test_forecast = model.forecast(N_TEST)
    test_forecast.index = test.index
    test_forecast = test_forecast.clip(lower=0)  # daily case counts can't be negative
    mae, rmse, mape = evaluate(test, test_forecast)

    # Refit on the FULL series (including the held-out window) before
    # forecasting genuinely new days, so the final forecast uses
    # every real day of data available.
    final_model = ExponentialSmoothing(
        series, trend="add", seasonal="add", seasonal_periods=7,
        damped_trend=True,
    ).fit()
    future_forecast = final_model.forecast(N_FORECAST).clip(lower=0)  # daily case counts can't be negative

    plt.figure(figsize=(12, 5))
    series.tail(120).plot(label="Actual", color="steelblue")
    test_forecast.plot(label=f"Forecast on held-out last {N_TEST} days", color="orange", linestyle="--")
    future_forecast.plot(label=f"Forecast: next {N_FORECAST} days beyond dataset", color="firebrick")
    plt.title(f"Daily new confirmed cases - {COUNTRY} (Holt-Winters forecast)")
    plt.ylabel("new cases per day")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "forecast_cases.png", dpi=150)
    plt.close()

    report = [
        "# Time Series Forecasting Report (Task 6)",
        f"\nSeries: daily new confirmed cases - {COUNTRY}",
        "\nModel: Holt-Winters Exponential Smoothing (additive trend,",
        "additive weekly seasonality, damped trend, seasonal_periods=7)",
        f"\n## Validation (last {N_TEST} days held out)",
        f"- MAE:  {mae:,.0f} cases/day",
        f"- RMSE: {rmse:,.0f} cases/day",
        f"- MAPE: {mape:.1f}%",
        f"\n## Forecast for the next {N_FORECAST} days beyond the last reported date\n",
        "```",
        future_forecast.round(0).to_string(),
        "```",
        "\n\nNote: JHU stopped updating this dataset in March 2023, so",
        "'future' here means the days right after the dataset's last",
        "recorded date - not the actual present day.",
    ]
    (OUTPUT_DIR / "forecast_report.md").write_text("\n".join(report))
    print(f"MAE={mae:,.0f}  RMSE={rmse:,.0f}  MAPE={mape:.1f}%")
    print(f"Saved chart + report to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()