-- One-time setup:
CREATE DATABASE IF NOT EXISTS COVID_PROJECT;
CREATE SCHEMA IF NOT EXISTS COVID_PROJECT.ANALYTICS;

SHOW SCHEMAS IN DATABASE COVID_PROJECT;


-- Build the country-level enrichment base.
-- Population and ISO code come from ECDC_GLOBAL (2019 figures,
-- already inside the marketplace dataset), so per-capita rates use
-- a denominator contemporary with the pandemic period (2020-2023).
-- A name-normalization map bridges the cases where JHU and ECDC
-- spell the same country differently (Bahamas, Cabo Verde,
-- Timor-Leste, Gambia, United_Kingdom, Syria, Congo), reaching
-- 198 matched countries. Remaining unmatched JHU entries are
-- non-country entities (cruise ships, Olympics categories),
-- French overseas regions counted under France, and small Pacific
-- states outside ECDC's coverage.


CREATE OR REPLACE TABLE COVID_PROJECT.ANALYTICS.COUNTRY_BASE AS
WITH jhu_latest AS (
    SELECT COUNTRY_REGION, CUM_CONFIRMED, CUM_DEATHS, DATE,
           -- normalized name used ONLY for the join to ECDC
           CASE COUNTRY_REGION
               WHEN 'Bahamas, The'          THEN 'Bahamas'
               WHEN 'Cape Verde'            THEN 'Cabo Verde'
               WHEN 'East Timor'            THEN 'Timor-Leste'
               WHEN 'The Gambia'            THEN 'Gambia'
               WHEN 'United Kingdom'        THEN 'United_Kingdom'
               WHEN 'Syria'                 THEN 'Syrian Arab Republic'
               WHEN 'Republic of the Congo' THEN 'Congo'
               ELSE COUNTRY_REGION
           END AS JOIN_NAME
    FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COUNTRY_REGION ORDER BY DATE DESC
    ) = 1
),
ecdc_pop AS (
    SELECT COUNTRY_REGION,
           MAX(ISO3166_1)   AS ISO_CODE,
           MAX(CONTINENTEXP) AS REGION,
           MAX(POPULATION)  AS POPULATION_2019
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
    WHERE POPULATION IS NOT NULL AND POPULATION > 0
    GROUP BY COUNTRY_REGION
)
SELECT j.COUNTRY_REGION,           
       e.ISO_CODE,
       e.REGION,
       j.DATE,
       j.CUM_CONFIRMED,
       j.CUM_DEATHS,
       e.POPULATION_2019 AS POPULATION,
       j.CUM_CONFIRMED / e.POPULATION_2019 * 100000 AS CASES_PER_100K,
       j.CUM_DEATHS     / e.POPULATION_2019 * 100000 AS DEATHS_PER_100K
FROM jhu_latest j
JOIN ecdc_pop e ON j.JOIN_NAME = e.COUNTRY_REGION;

--  how many countries matched? 
SELECT COUNT(*) AS matched_countries FROM COVID_PROJECT.ANALYTICS.COUNTRY_BASE;

-- Spot-check the recovered + corrected countries
SELECT COUNTRY_REGION, ISO_CODE, POPULATION, ROUND(DEATHS_PER_100K, 1) AS DEATHS_PER_100K
FROM COVID_PROJECT.ANALYTICS.COUNTRY_BASE
WHERE COUNTRY_REGION IN ('United Kingdom', 'Syria', 'Republic of the Congo',
                         'Cape Verde', 'Turkey', 'Latvia')
ORDER BY COUNTRY_REGION;