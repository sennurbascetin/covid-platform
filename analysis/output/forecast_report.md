# Time Series Forecasting Report (Task 6)

Series: daily new confirmed cases - Turkey

Model: Holt-Winters Exponential Smoothing (additive trend,
additive weekly seasonality, damped trend, seasonal_periods=7)

## Validation (last 30 days held out)
- MAE:  4,594 cases/day
- RMSE: 22,497 cases/day
- MAPE: 100.0%

## Forecast for the next 30 days beyond the last reported date

```
2023-01-02    10957.0
2023-01-03    11594.0
2023-01-04    13533.0
2023-01-05    16436.0
2023-01-06    14519.0
2023-01-07    14077.0
2023-01-08    12045.0
2023-01-09    14296.0
2023-01-10    14482.0
2023-01-11    16030.0
2023-01-12    18596.0
2023-01-13    16388.0
2023-01-14    15693.0
2023-01-15    13443.0
2023-01-16    15505.0
2023-01-17    15528.0
2023-01-18    16935.0
2023-01-19    19379.0
2023-01-20    17064.0
2023-01-21    16278.0
2023-01-22    13949.0
2023-01-23    15943.0
2023-01-24    15907.0
2023-01-25    17263.0
2023-01-26    19662.0
2023-01-27    17310.0
2023-01-28    16490.0
2023-01-29    14133.0
2023-01-30    16102.0
2023-01-31    16044.0
Freq: D
```


Note: JHU stopped updating this dataset in March 2023, so
'future' here means the days right after the dataset's last
recorded date - not the actual present day.