

-- ============================================================
-- Task 2a: Data Exploration
-- Goal: understand the structure, patterns and gaps in the
-- Snowflake COVID-19 marketplace dataset before building on it.
-- Author: Sennur Bascetin
-- ============================================================

-- 1) What columns does ECDC_GLOBAL have and what are their types?
DESC TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL;

-- 2) Date coverage + country count for ECDC

SELECT MIN(DATE)  AS first_date,
       MAX(DATE)  AS last_date,
       COUNT(DISTINCT COUNTRY_REGION) AS num_countries,
       COUNT(*)   AS total_rows
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL;

-- 3) Same structure check for the JHU table
DESC TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;

-- 4) A few sample rows from JHU to see actual values
SELECT * FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19 LIMIT 10;

-- 5) JHU keeps different metrics in one table via CASE_TYPE,

SELECT CASE_TYPE,
       MIN(DATE) AS first_date,
       MAX(DATE) AS last_date,
       COUNT(*)  AS total_rows
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19
GROUP BY CASE_TYPE;

-- 6) Gap check #1: negative daily numbers.

SELECT COUNT_IF(CASES < 0)  AS negative_case_rows,
       COUNT_IF(DEATHS < 0) AS negative_death_rows
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL;

-- 7) Gap check #2: are any days missing for a single country?
-- Using Latvia as a test case: actual rows vs expected day count
SELECT COUNT(*) AS actual_days,
       DATEDIFF('day', MIN(DATE), MAX(DATE)) + 1 AS expected_days
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE COUNTRY_REGION = 'Latvia';

-- 8) First pattern: monthly global case trend
-- (switching the result view to a line chart shows the waves)
SELECT DATE_TRUNC('month', DATE) AS month_start,
       SUM(CASES) AS total_cases
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
GROUP BY month_start
ORDER BY month_start;

-- 9) Top 10 countries by total cases and deaths
SELECT COUNTRY_REGION,
       SUM(CASES)  AS total_cases,
       SUM(DEATHS) AS total_deaths
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
GROUP BY COUNTRY_REGION
ORDER BY total_cases DESC
LIMIT 10;

-- 10) Peeking at DEMOGRAPHICS , candidate for enrichment later on
SELECT * FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.DEMOGRAPHICS LIMIT 10;