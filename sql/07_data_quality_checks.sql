-- A) Does either table carry an ISO country code? (an exact join key
-- would be much safer than the fuzzy name matching used so far)
DESC TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL;

DESC TABLE COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.JHU_COVID_19;

-- B) Sanity-check ECDC's population figures for familiar countries
SELECT COUNTRY_REGION, MAX(POPULATION) AS POPULATION
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE COUNTRY_REGION ILIKE ANY ('%Turkey%', '%Latvia%', '%United_States%',
                                '%United States%', '%Nigeria%', '%Germany%')
GROUP BY COUNTRY_REGION
ORDER BY COUNTRY_REGION;

-- C) How many countries actually have a usable population value?
SELECT COUNT(DISTINCT COUNTRY_REGION) AS countries_with_population
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE POPULATION IS NOT NULL AND POPULATION > 0;

-- D) How do ECDC country names look vs JHU? Need a bridge between
-- JHU (case data, no ISO code) and ECDC (population + ISO code).
SELECT DISTINCT COUNTRY_REGION, ISO3166_1
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE COUNTRY_REGION ILIKE ANY ('%Turkey%', '%Latvia%', '%United%', '%Czech%', '%Korea%')
ORDER BY COUNTRY_REGION;

-- E) Does the pre-aggregated JHU table (Task 7) cover the same names?
SELECT DISTINCT COUNTRY_REGION
FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
WHERE COUNTRY_REGION ILIKE ANY ('%Turkey%', '%Latvia%', '%United%', '%Czech%', '%Korea%')
ORDER BY COUNTRY_REGION;

-- F) How many distinct countries in each table on its own?
SELECT 'ECDC (has population)' AS source,
       COUNT(DISTINCT COUNTRY_REGION) AS n
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE POPULATION IS NOT NULL AND POPULATION > 0
UNION ALL
SELECT 'JHU daily (Task 7 table)', COUNT(DISTINCT COUNTRY_REGION)
FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
UNION ALL
SELECT 'COUNTRY_BASE (matched now)', COUNT(*)
FROM COVID_PROJECT.ANALYTICS.COUNTRY_BASE;

-- G) Which JHU countries did NOT match into COUNTRY_BASE?
-- These are the ones we're "losing" - let's see if they're real
-- countries with a name mismatch, or genuinely missing from ECDC.
SELECT DISTINCT j.COUNTRY_REGION AS jhu_name
FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY j
LEFT JOIN COVID_PROJECT.ANALYTICS.COUNTRY_BASE b
       ON j.COUNTRY_REGION = b.COUNTRY_REGION
WHERE b.COUNTRY_REGION IS NULL
ORDER BY jhu_name;

-- H) Full list of the 25 unmatched JHU names, side by side with
-- ECDC's country names, so I can see which are fixable name
-- mismatches vs genuinely absent from ECDC.
SELECT DISTINCT j.COUNTRY_REGION AS jhu_name
FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY j
LEFT JOIN COVID_PROJECT.ANALYTICS.COUNTRY_BASE b
       ON j.COUNTRY_REGION = b.COUNTRY_REGION
WHERE b.COUNTRY_REGION IS NULL
ORDER BY jhu_name;

-- I) All ECDC country names, so I can find the correct spelling to
-- map each fixable JHU name to.
SELECT DISTINCT COUNTRY_REGION
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE POPULATION IS NOT NULL AND POPULATION > 0
ORDER BY COUNTRY_REGION;

-- J) Is Syria actually in ECDC under a different spelling? Same
-- check for the other unmatched names that ARE real countries
-- (small Pacific states, North Korea, Congo) - maybe some are
-- fixable name mismatches, not genuine absences.
SELECT DISTINCT COUNTRY_REGION, ISO3166_1, MAX(POPULATION) AS POPULATION
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE COUNTRY_REGION ILIKE ANY (
        '%Syria%', '%Korea%', '%Congo%', '%Kiribati%', '%Micronesia%',
        '%Nauru%', '%Palau%', '%Samoa%', '%Tonga%', '%Tuvalu%'
      )
GROUP BY COUNTRY_REGION, ISO3166_1
ORDER BY COUNTRY_REGION;

-- K) Double-check the small Pacific states really aren't in ECDC
-- under any spelling before giving up on them.
SELECT DISTINCT COUNTRY_REGION, ISO3166_1, MAX(POPULATION) AS POPULATION
FROM COVID19_EPIDEMIOLOGICAL_DATA.PUBLIC.ECDC_GLOBAL
WHERE COUNTRY_REGION ILIKE ANY (
        '%Kiriba%', '%Nauru%', '%Palau%', '%Samoa%', '%Tonga%',
        '%Tuvalu%', '%Micron%', '%Marshall%', '%Solomon%'
      )
GROUP BY COUNTRY_REGION, ISO3166_1
ORDER BY COUNTRY_REGION;