# Second enrichment pass: Our World in Data (external dataset).
# Runs AFTER enrich_data.py and adds the variables neither Snowflake
# nor the Kaggle CSV provides well:
#   - gdp_per_capita: replaces Kaggle's ~2006 figure, which was wrong
#     by a factor of 5 for some countries (Qatar: 21,500 vs 110,890)
#   - median_age: the single strongest confounder for death rates
#   - people_vaccinated_per_hundred: vaccination coverage
#   - excess mortality: deaths above the pre-pandemic baseline, which
#     is independent of how a country classified COVID deaths
# Population stays on ECDC's 2019 figure - it is the denominator for
# the per-100k rates and must match the pandemic period, whereas
# OWID's population column is a current-year estimate. Literacy stays
# on Kaggle, which OWID does not carry.
#
# Input: data/owid_country_static.csv - one row per country, produced
# by distill_owid.py from OWID's full 170 MB export (too large to
# commit). The full export is still accepted if present.
#
# Matching is two-pass: OWID uses ISO3 (TUR) while COUNTRY_ENRICHED
# carries ECDC's ISO2 (TR), so codes are converted with pycountry;
# rows the code cannot resolve fall back to matching on country name.
# Three countries need that fallback: Greece (ECDC uses the EU code
# EL, not GR), Namibia (ISO2 "NA", which gets read as a null value),
# and Kosovo (no standard ISO code at all).

from pathlib import Path

import pandas as pd
import pycountry
from snowflake.connector.pandas_tools import write_pandas

from sf_connect import get_connection, fetch_df

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Prefer the small distilled file that ships with the repo; fall back
# to the full export if someone re-downloaded it.
DISTILLED = DATA_DIR / "owid_country_static.csv"
FULL_EXPORT = DATA_DIR / "owid_covid.csv"
OWID_CSV = DISTILLED if DISTILLED.exists() else FULL_EXPORT

# Static per-country columns: identical on every row of the full
# export, so the last row wins.
STATIC_COLS = {
    "gdp_per_capita": "GDP_PER_CAPITA_OWID",
    "median_age": "MEDIAN_AGE",
    "life_expectancy": "LIFE_EXPECTANCY",
    "hospital_beds_per_thousand": "HOSPITAL_BEDS_PER_1K",
    "diabetes_prevalence": "DIABETES_PCT",
    "population_density": "POPULATION_DENSITY",
}

# Sparse time-series columns: take the last row that actually has a value.
LATEST_COLS = {
    "people_vaccinated_per_hundred": "VACCINATED_PCT",
    "people_fully_vaccinated_per_hundred": "FULLY_VACCINATED_PCT",
    "excess_mortality_cumulative_per_million": "EXCESS_DEATHS_PER_MILLION",
}

# pycountry returns the ISO standard code; ECDC stores a different one
# for a few countries, so translate back to what our table holds.
ISO_OVERRIDES = {"GB": "UK", "GR": "EL"}


def iso3_to_iso2(code):
    if not isinstance(code, str) or len(code) != 3:
        return None
    try:
        iso2 = pycountry.countries.get(alpha_3=code).alpha_2
    except (AttributeError, LookupError):
        return None
    return ISO_OVERRIDES.get(iso2, iso2)


def load_owid() -> pd.DataFrame:
    if not OWID_CSV.exists():
        raise FileNotFoundError(
            f"Expected OWID data at {DISTILLED}. Download the full export "
            "from https://catalog.ourworldindata.org/garden/covid/latest/"
            "compact/compact.csv and run analysis/distill_owid.py."
        )

    df = pd.read_csv(OWID_CSV)

    # The distilled file already has one row per country. The full
    # export has one row per country-day, so collapse it the same way
    # distill_owid.py does.
    if "date" in df.columns:
        keep = df["code"].notna() & (
            (df["code"].str.len() == 3) | (df["country"] == "Kosovo"))
        df = df[keep].sort_values("date")
        rows = []
        for code, grp in df.groupby("code"):
            last = grp.iloc[-1]
            record = {"code": code, "country": last["country"]}
            for src in list(STATIC_COLS) + list(LATEST_COLS):
                real = grp[grp[src].notna()]
                record[src] = real[src].iloc[-1] if not real.empty else None
            rows.append(record)
        df = pd.DataFrame(rows)

    df = df.rename(columns={**STATIC_COLS, **LATEST_COLS})
    df["ISO_CODE"] = df["code"].apply(iso3_to_iso2)
    df["OWID_NAME"] = df["country"]
    return df.drop(columns=["code", "country"])


def main():
    conn = get_connection()
    try:
        base = fetch_df(conn, "SELECT * FROM COVID_PROJECT.ANALYTICS.COUNTRY_ENRICHED")
        print(f"COUNTRY_ENRICHED rows before: {len(base)}")
        print(f"OWID source: {OWID_CSV.name}")

        owid = load_owid()
        print(f"OWID countries parsed: {len(owid)}")

        value_cols = [c for c in owid.columns if c not in ("ISO_CODE", "OWID_NAME")]
        by_iso = (owid.dropna(subset=["ISO_CODE"])
                      .drop_duplicates(subset=["ISO_CODE"])
                      .set_index("ISO_CODE"))
        by_name = owid.drop_duplicates(subset=["OWID_NAME"]).set_index("OWID_NAME")

        stats = {"iso": 0, "name": 0, "none": 0}
        unmatched = []

        def lookup(row):
            iso = row.get("ISO_CODE")
            if isinstance(iso, str) and iso in by_iso.index:
                stats["iso"] += 1
                return by_iso.loc[iso, value_cols]
            name = row.get("COUNTRY_REGION")
            if name in by_name.index:
                stats["name"] += 1
                return by_name.loc[name, value_cols]
            stats["none"] += 1
            unmatched.append(name)
            return pd.Series({c: None for c in value_cols})

        extra = base.apply(lookup, axis=1)
        merged = pd.concat([base, extra], axis=1)

        print(f"Matched by ISO code: {stats['iso']}")
        print(f"Matched by country name (ISO fallback): {stats['name']}")
        print(f"Not matched: {stats['none']}")
        if unmatched:
            print("  ->", ", ".join(sorted(str(u) for u in unmatched)))

        # OWID's GDP replaces Kaggle's where available; Kaggle stays as
        # the fallback so no country loses the column entirely.
        merged["GDP_PER_CAPITA"] = merged["GDP_PER_CAPITA_OWID"].fillna(
            merged["GDP_PER_CAPITA"])
        merged = merged.drop(columns=["GDP_PER_CAPITA_OWID"])

        merged.columns = [c.upper() for c in merged.columns]
        write_pandas(
            conn, merged,
            table_name="COUNTRY_ENRICHED",
            database="COVID_PROJECT", schema="ANALYTICS",
            auto_create_table=True, overwrite=True,
        )
        print(f"\nWrote {len(merged)} rows back to COUNTRY_ENRICHED.")

        check = merged[merged["COUNTRY_REGION"].isin(
            ["Turkey", "Latvia", "Qatar", "Greece", "Namibia", "Kosovo"])]
        cols = ["COUNTRY_REGION", "GDP_PER_CAPITA", "MEDIAN_AGE",
                "VACCINATED_PCT", "EXCESS_DEATHS_PER_MILLION"]
        print("\n" + check[cols].to_string(index=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()