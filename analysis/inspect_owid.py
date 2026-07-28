# One-off inspection of the OWID COVID dataset before integrating it.
# One-off exploration, not part of the pipeline
# The current OWID schema uses `country`/`code` (older versions used
# `location`/`iso_code`), so this prints what actually exists plus a
# sample for the countries I care about.

from pathlib import Path

import pandas as pd

CSV = Path(__file__).resolve().parents[1] / "data" / "owid_covid.csv"

WANTED = [
    "code", "country", "continent", "date", "population",
    "gdp_per_capita", "median_age", "life_expectancy",
    "human_development_index", "hospital_beds_per_thousand",
    "diabetes_prevalence", "population_density", "extreme_poverty",
    "stringency_index",
    "people_vaccinated_per_hundred", "people_fully_vaccinated_per_hundred",
    "total_deaths_per_million", "total_cases_per_million",
    "excess_mortality_cumulative_per_million",
]


def main():
    if not CSV.exists():
        raise FileNotFoundError(f"Expected the OWID CSV at {CSV}")

    header = pd.read_csv(CSV, nrows=0)
    cols = list(header.columns)
    print(f"Total columns in file: {len(cols)}\n")

    present = [c for c in WANTED if c in cols]
    missing = [c for c in WANTED if c not in cols]

    print("WANTED columns that EXIST:")
    for c in present:
        print(f"  + {c}")
    print("\nWANTED columns that are MISSING:")
    for c in missing:
        print(f"  - {c}")

    df = pd.read_csv(CSV, usecols=present)
    print(f"\nRows in file: {len(df):,}")

    loc_col = "country"

    # How is Turkey spelled here, and what does `code` look like?
    names = sorted(n for n in df[loc_col].unique()
                   if str(n).lower().startswith(("turk", "tür", "latv", "qat")))
    print(f"\nMatching country names found: {names}")

    for country in names:
        sub = df[df[loc_col] == country]
        if sub.empty:
            continue
        # last row that actually has a GDP value, so static columns show up
        last = sub.sort_values("date").iloc[-1]
        print(f"\n--- {country} (last row, {last['date']}) ---")
        for c in present:
            if c not in ("date", loc_col):
                print(f"  {c}: {last[c]}")

        # static columns are repeated on every row; vaccination and
        # excess mortality are sparse, so report their last real value
        for c in ("people_vaccinated_per_hundred",
                  "excess_mortality_cumulative_per_million"):
            if c in sub.columns:
                real = sub[sub[c].notna()]
                if not real.empty:
                    r = real.sort_values("date").iloc[-1]
                    print(f"  [last non-empty] {c}: {r[c]}  (on {r['date']})")
                else:
                    print(f"  [last non-empty] {c}: none in file")


if __name__ == "__main__":
    main()