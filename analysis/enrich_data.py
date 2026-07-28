# Task 2b: Enrichment.
# Reads COUNTRY_BASE (country-level cases/deaths + ECDC population +
# ISO code + per-100k rates, built in 03_workspace_setup.sql) and
# adds the two variables the marketplace dataset lacks: GDP per
# capita and literacy rate, from the Kaggle "Countries of the World"
# CSV, matched on normalized country name. Writes the result as
# COVID_PROJECT.ANALYTICS.COUNTRY_ENRICHED for the API to query.
# Population comes from ECDC (2019) rather than the Kaggle CSV; GDP
# and literacy stay on Kaggle since the marketplace dataset does not
# carry them.

import unicodedata
from pathlib import Path

import pandas as pd
from snowflake.connector.pandas_tools import write_pandas

from sf_connect import get_connection, fetch_df

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

KAGGLE_CSV = DATA_DIR / "countries_of_the_world.csv"

# Kaggle uses CIA World Factbook names; map its name (lowercase,
# accents stripped) -> the JHU name already used in COUNTRY_BASE, so
# GDP/literacy attach to the right row.
NAME_FIXES = {
    "united states": "us",
    "bahamas, the": "bahamas, the",
    "cape verde": "cape verde",
    "congo, repub. of the": "republic of the congo",
    "congo, dem. rep.": "congo (kinshasa)",
    "korea, south": "korea, republic of",
    "gambia, the": "the gambia",
    "east timor": "east timor",
    "syria": "syria",
    "myanmar": "burma",
    "russia": "russia",
    "czech republic": "czechia",
    "macedonia": "north macedonia",
    "swaziland": "eswatini",
}


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def normalize(name: str) -> str:
    key = strip_accents(str(name).strip().lower())
    return NAME_FIXES.get(key, key)


def load_kaggle_gdp_literacy() -> pd.DataFrame:
    if not KAGGLE_CSV.exists():
        raise FileNotFoundError(
            f"Expected the Kaggle CSV at {KAGGLE_CSV}."
        )
    df = pd.read_csv(KAGGLE_CSV)
    df.columns = df.columns.str.strip()

    required = {"Country", "GDP ($ per capita)", "Literacy (%)"}
    missing = required - set(df.columns)
    if missing:
        raise KeyError(f"Missing columns {missing}. Have: {list(df.columns)}")

    # European-style decimals ("23,06") -> float
    for col in ("GDP ($ per capita)", "Literacy (%)"):
        if df[col].dtype == "object":
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["Country"] = df["Country"].str.strip()
    df["MATCH_KEY"] = df["Country"].apply(normalize)
    return df[["MATCH_KEY", "GDP ($ per capita)", "Literacy (%)"]].rename(
        columns={"GDP ($ per capita)": "GDP_PER_CAPITA", "Literacy (%)": "LITERACY_PCT"}
    )


def main():
    conn = get_connection()
    try:
        base = fetch_df(conn, "SELECT * FROM COVID_PROJECT.ANALYTICS.COUNTRY_BASE")
        base["MATCH_KEY"] = base["COUNTRY_REGION"].apply(normalize)

        kaggle = load_kaggle_gdp_literacy()
        merged = base.merge(kaggle, on="MATCH_KEY", how="left", indicator=True)

        matched = merged["_merge"].eq("both").sum()
        print(f"COUNTRY_BASE rows: {len(base)}")
        print(f"Rows that also got GDP/literacy from Kaggle: {matched}")

        enriched = merged[[
            "COUNTRY_REGION", "ISO_CODE","REGION" , "DATE", "CUM_CONFIRMED", "CUM_DEATHS",
            "POPULATION", "CASES_PER_100K", "DEATHS_PER_100K",
            "GDP_PER_CAPITA", "LITERACY_PCT",
        ]].copy()
        enriched.columns = [c.upper() for c in enriched.columns]

        write_pandas(
            conn, enriched,
            table_name="COUNTRY_ENRICHED",
            database="COVID_PROJECT", schema="ANALYTICS",
            auto_create_table=True, overwrite=True,
        )
        print(f"Wrote {len(enriched)} rows to COVID_PROJECT.ANALYTICS.COUNTRY_ENRICHED.")

        # Quick insight for the report: GDP vs deaths correlation
        corr = enriched[["GDP_PER_CAPITA", "DEATHS_PER_100K"]].corr().iloc[0, 1]
        print(f"Correlation GDP per capita vs deaths per 100k: {corr:.2f}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()