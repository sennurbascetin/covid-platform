# Reduces the full OWID export (~170 MB, 600k rows) to the one row
# per country that the enrichment actually uses. The result is small
# enough to commit, so the pipeline can be re-run from a fresh clone
# without downloading the full file.
#
# Run once after downloading the OWID CSV:
#     python analysis/distill_owid.py

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SOURCE = DATA_DIR / "owid_covid.csv"
TARGET = DATA_DIR / "owid_country_static.csv"

STATIC_COLS = ["gdp_per_capita", "median_age", "life_expectancy",
               "hospital_beds_per_thousand", "diabetes_prevalence",
               "population_density"]
LATEST_COLS = ["people_vaccinated_per_hundred",
               "people_fully_vaccinated_per_hundred",
               "excess_mortality_cumulative_per_million"]


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(
            f"Expected the full OWID export at {SOURCE}. Download it from "
            "https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv"
        )

    df = pd.read_csv(SOURCE, usecols=["code", "country", "date"] + STATIC_COLS + LATEST_COLS)

    # Keep real countries only: OWID aggregates (continents, World,
    # income groups) carry an OWID_ prefixed code. Kosovo has no ISO
    # code at all but is a real entry, so it is kept explicitly.
    keep = df["code"].notna() & ((df["code"].str.len() == 3) | (df["country"] == "Kosovo"))
    df = df[keep].sort_values("date")

    rows = []
    for code, grp in df.groupby("code"):
        last = grp.iloc[-1]
        record = {"code": code, "country": last["country"]}
        for c in STATIC_COLS:
            record[c] = last[c]
        # vaccination and excess mortality stop being reported before
        # the end of the file, so take the last non-empty value
        for c in LATEST_COLS:
            real = grp[grp[c].notna()]
            record[c] = real[c].iloc[-1] if not real.empty else None
        rows.append(record)

    out = pd.DataFrame(rows)
    out.to_csv(TARGET, index=False)
    size_kb = TARGET.stat().st_size / 1024
    print(f"{len(df):,} rows -> {len(out)} countries")
    print(f"Written to {TARGET.name} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()