-- ============================================================
-- Task 9: Pattern Recognition with MATCH_RECOGNIZE
-- Question: when did each country's COVID waves happen, and how
-- long did they last?
-- A "wave" here = at least 3 consecutive WEEKS of rising new
-- cases followed by at least 2 consecutive weeks of decline.
-- Weekly buckets (not daily) because day-level data is too noisy
-- for run-length patterns - weekend reporting dips would break
-- every RISE sequence.
-- ============================================================

-- Step 1: weekly new cases per country, derived from the
-- pre-aggregated daily table built in Task 7.
CREATE OR REPLACE VIEW COVID_PROJECT.ANALYTICS.WEEKLY_NEW_CASES AS
SELECT COUNTRY_REGION,
       DATE_TRUNC('week', DATE)                          AS WEEK_START,
       GREATEST(MAX(CUM_CONFIRMED) - MIN(CUM_CONFIRMED), 0) AS NEW_CASES
FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
GROUP BY COUNTRY_REGION, WEEK_START;

-- Step 2: find wave patterns. MATCH_RECOGNIZE walks through each
-- country's weeks in order (PARTITION BY country, ORDER BY week)
-- and hunts for the sequence: 3+ rising weeks then 2+ falling.
SELECT *
FROM COVID_PROJECT.ANALYTICS.WEEKLY_NEW_CASES
MATCH_RECOGNIZE (
    PARTITION BY COUNTRY_REGION
    ORDER BY WEEK_START
    MEASURES
        FIRST(WEEK_START)      AS wave_start,
        LAST(WEEK_START)       AS wave_end,
        COUNT(*)               AS weeks_total,
        COUNT(RISE.*)          AS weeks_rising,
        MAX(NEW_CASES)         AS peak_weekly_cases
    ONE ROW PER MATCH
    AFTER MATCH SKIP PAST LAST ROW
    PATTERN (RISE RISE RISE+ FALL FALL+)
    DEFINE
        RISE AS NEW_CASES > LAG(NEW_CASES),
        FALL AS NEW_CASES < LAG(NEW_CASES)
)
ORDER BY COUNTRY_REGION, wave_start;

-- Step 3: same engine, different question - Latvia's waves only,
-- to read one familiar country's pandemic story line by line.
SELECT *
FROM COVID_PROJECT.ANALYTICS.WEEKLY_NEW_CASES
MATCH_RECOGNIZE (
    PARTITION BY COUNTRY_REGION
    ORDER BY WEEK_START
    MEASURES
        FIRST(WEEK_START)      AS wave_start,
        LAST(WEEK_START)       AS wave_end,
        COUNT(*)               AS weeks_total,
        MAX(NEW_CASES)         AS peak_weekly_cases
    ONE ROW PER MATCH
    AFTER MATCH SKIP PAST LAST ROW
    PATTERN (RISE RISE RISE+ FALL FALL+)
    DEFINE
        RISE AS NEW_CASES > LAG(NEW_CASES),
        FALL AS NEW_CASES < LAG(NEW_CASES)
) 
WHERE COUNTRY_REGION = 'Latvia'
ORDER BY wave_start;

-- Step 4: aggregate insight - which countries were hit by the
-- most distinct waves?
SELECT COUNTRY_REGION,
       COUNT(*)                    AS wave_count,
       MAX(peak_weekly_cases)      AS worst_week_ever
FROM (
    SELECT *
    FROM COVID_PROJECT.ANALYTICS.WEEKLY_NEW_CASES
    MATCH_RECOGNIZE (
        PARTITION BY COUNTRY_REGION
        ORDER BY WEEK_START
        MEASURES
            FIRST(WEEK_START) AS wave_start,
            MAX(NEW_CASES)    AS peak_weekly_cases
        ONE ROW PER MATCH
        AFTER MATCH SKIP PAST LAST ROW
        PATTERN (RISE RISE RISE+ FALL FALL+)
        DEFINE
            RISE AS NEW_CASES > LAG(NEW_CASES),
            FALL AS NEW_CASES < LAG(NEW_CASES)
    )
)
GROUP BY COUNTRY_REGION
ORDER BY wave_count DESC
LIMIT 15;