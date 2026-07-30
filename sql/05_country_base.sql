
-- Builds COUNTRY_BASE: latest cumulative figures per country joined
-- to ECDC's 2019 population, ISO code and continent.
-- DEPENDS ON: 04_optimization.sql (creates JHU_DAILY_COUNTRY first).
--
-- Population and ISO code come from ECDC_GLOBAL (2019 figures,
-- already inside the marketplace dataset), so per-capita rates use
-- a denominator contemporary with the pandemic period (2020-2023),
-- not Kaggle's ~2006 snapshot.
--
-- A name-normalization map bridges the cases where JHU and ECDC
-- spell the same country differently (Bahamas, Cabo Verde,
-- Timor-Leste, Gambia, United_Kingdom, Syria, Congo), reaching
-- 198 matched countries. Remaining unmatched JHU entries are
-- non-country entities (cruise ships, Olympics categories), French
-- overseas regions counted under France, and small Pacific states
-- outside ECDC's coverage.


CREATE OR REPLACE TABLE COVID_PROJECT.ANALYTICS.COUNTRY_BASE AS
WITH jhu_latest AS (
    SELECT
        COUNTRY_REGION,
        CUM_CONFIRMED,
        CUM_DEATHS,
        DATE,
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
    SELECT
        COUNTRY_REGION,
        MAX(ISO3166_1)    AS ISO_CODE,
        MAX(CONTINENTEXP) AS REGION,
        MAX(POPULATION)   AS POPULATION_2019
    FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
    WHERE POPULATION IS