# Shared Snowflake connection + query helper.
# Every script in this project imports from here, so the connection
# logic, credentials, and the Decimal-cleanup all live in one single
# place instead of being copy-pasted into every script.

import os
from pathlib import Path

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def get_connection():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        private_key_file=str(ROOT / os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE")),
        role=os.getenv("SNOWFLAKE_ROLE"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )


def fetch_df(conn, query):
    """Run a query and return the result as a clean pandas dataframe.

    Handles two recurring Snowflake quirks in one place:
    - DATE columns arrive as strings -> parsed to real dates.
    - NUMBER columns sometimes arrive as Python Decimal (dtype
      'object') -> converted to real numeric dtypes so pandas can
      compute stats and comparisons on them.
    """
    cur = conn.cursor()
    cur.execute(query)
    df = cur.fetch_pandas_all()

    if "DATE" in df.columns:
        df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")

    for col in df.columns:
        if df[col].dtype == "object" and col != "COUNTRY_REGION":
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass  # genuinely non-numeric column, leave as text

    return df