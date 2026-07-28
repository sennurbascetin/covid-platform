-- ============================================================
-- Task 7: Performance Optimization
-- The marketplace database is read-only, so JHU_COVID_19 itself
-- can't be altered (no clustering keys, no materialized views on
-- it). Optimization strategy instead:
--   1. measure a baseline for the heaviest query the API runs,
--   2. pre-aggregate that workload ONCE into a summary table in
--      my own database - later queries read the small table,
--   3. demonstrate Snowflake's result cache,
--   4. tune the warehouse so it stops burning credits when idle.
-- ============================================================

-- Result cache OFF while benchmarking - otherwise repeat runs
-- would just replay a stored result and the timings would be fake.
ALTER SESSION SET USE_CACHED_RESULT = FALSE;

-- 1) BASELINE: the exact aggregation the API does for
-- /covid/{country}, straight against the raw shared table.
SELECT DATE,
       SUM(IFF(CASE_TYPE = 'Confirmed', CASES, 0)) AS CUM_CONFIRMED,
       SUM(IFF(CASE_TYPE = 'Deaths',    CASES, 0)) AS CUM_DEATHS
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE CASE_TYPE IN ('Confirmed', 'Deaths')
  AND COUNTRY_REGION = 'Peru'
GROUP BY DATE
ORDER BY DATE;

-- 2) OPTIMIZATION: collapse the province-level table down to
-- (country, date) ONCE, into my own database. This computation
-- used to happen on every single API request; now it happens
-- one time here.
CREATE OR REPLACE TABLE COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY AS
SELECT COUNTRY_REGION,
       DATE,
       SUM(IFF(CASE_TYPE = 'Confirmed', CASES, 0)) AS CUM_CONFIRMED,
       SUM(IFF(CASE_TYPE = 'Deaths',    CASES, 0)) AS CUM_DEATHS
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
WHERE CASE_TYPE IN ('Confirmed', 'Deaths')
GROUP BY COUNTRY_REGION, DATE;

-- 3) SAME QUESTION, OPTIMIZED PATH: now against the summary
-- table. Compare this duration with the baseline above.
SELECT DATE, CUM_CONFIRMED, CUM_DEATHS
FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
WHERE COUNTRY_REGION = 'Peru'
ORDER BY DATE;

-- 4) RESULT CACHE: switch it back on, then run the SELECT below
-- TWICE. The second run is served from Snowflake's result cache
-- without touching the warehouse at all - it should return in
-- a few milliseconds.
ALTER SESSION SET USE_CACHED_RESULT = TRUE;

SELECT DATE, CUM_CONFIRMED, CUM_DEATHS
FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
WHERE COUNTRY_REGION = 'Peru'
ORDER BY DATE;

-- 5) WAREHOUSE TUNING: suspend after 60s of inactivity instead
-- of the default 10 minutes. Doesn't make queries faster, but
-- stops the warehouse from spending credits between requests.
-- Trade-off: the first query after an idle period pays a short
-- (~1s) resume delay. Pairs with the Task 1 resource monitor.
ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;

-- 6) Deliberate NON-optimization, documented: clustering keys.
-- Snowflake recommends manual clustering only for very large
-- (multi-TB) tables. Both of my own tables are tiny compared to
-- that, so a clustering key would cost credits for zero gain.
SHOW TABLES IN COVID_PROJECT.ANALYTICS;