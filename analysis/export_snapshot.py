# Exports the two Snowflake tables the API needs into local Parquet
# files, so the platform still runs after the Snowflake trial expires
# (or on any machine without Snowflake credentials). The API prefers
# live Snowflake and falls back to this snapshot automatically.
#
# Run this once while Snowflake is still reachable:
#     python analysis/export_snapshot.py

from pathlib import Path

from sf_connect import get_connection, fetch_df

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "snapshot"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

TABLES = {
    "country_enriched": "SELECT * FROM COVID_PROJECT.ANALYTICS.COUNTRY_ENRICHED",
    "jhu_daily_country": "SELECT * FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY",
}


def main():
    conn = get_connection()
    try:
        for name, query in TABLES.items():
            df = fetch_df(conn, query)
            # dates as plain strings: identical shape to what the API
            # returns from Snowflake, so downstream code sees no change
            if "DATE" in df.columns:
                df["DATE"] = df["DATE"].astype(str).str[:10]
            out = SNAPSHOT_DIR / f"{name}.parquet"
            df.to_parquet(out, index=False)
            size_mb = out.stat().st_size / 1_048_576
            print(f"{name}: {len(df):,} rows -> {out.name} ({size_mb:.1f} MB)")
    finally:
        conn.close()
    print(f"\nSnapshot written to {SNAPSHOT_DIR}")


if __name__ == "__main__":
    main()