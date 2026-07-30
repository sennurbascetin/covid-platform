import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from cachetools import TTLCache
from typing import Optional

import numpy as np
import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# --- Offline snapshot -----------------------------------------------
# The Snowflake trial eventually expires, and a reviewer cloning this
# repo may not have Snowflake credentials at all. So the two tables
# every endpoint reads are also shipped as local Parquet files. The
# API always PREFERS live Snowflake and silently falls back to the
# snapshot only when Snowflake is unreachable - the dashboard never
# notices the difference because the dataframes are identical.
# FORCE_SNAPSHOT=1 forces the fallback path, which is how I verify it.
SNAPSHOT_DIR = Path(os.getenv("SNAPSHOT_DIR", ROOT / "data" / "snapshot"))
FORCE_SNAPSHOT = os.getenv("FORCE_SNAPSHOT", "").strip() in {"1", "true", "yes"}
# How long to stay on the snapshot before trying Snowflake again.
# Without this the first failure would pin the process to the
# snapshot until restart, because the Snowflake path only runs when
# sf_conn is not None.
SNOWFLAKE_RETRY_AFTER = 300  # seconds



# .env.example ships placeholders. Without this check a grader who
# copies it verbatim makes the API attempt a connection to an account
# that does not exist - at startup and again on every retry - and the
# connector's default login timeout can stall a request for a minute
# in the middle of a demo.
PLACEHOLDER_VALUES = {
    "", "ORGNAME-ACCOUNTNAME", "YOUR_SNOWFLAKE_USERNAME",
    "<YOUR_USER>", "<YOUR_USERNAME>",
}


def snowflake_configured() -> bool:
    """True only when .env holds real credentials and the key file
    exists. Anything else means: serve the snapshot, don't dial out."""
    account = (os.getenv("SNOWFLAKE_ACCOUNT") or "").strip()
    user = (os.getenv("SNOWFLAKE_USER") or "").strip()
    if account in PLACEHOLDER_VALUES or user in PLACEHOLDER_VALUES:
        return False
    key_file = os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE") or ""
    return bool(key_file) and (ROOT / key_file).exists()






def get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        private_key_file=str(ROOT / os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE")),
        role=os.getenv("SNOWFLAKE_ROLE"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
        # Fail fast instead of hanging a request for the connector's
        # default timeout when the account is unreachable.
        login_timeout=5,
        network_timeout=10,
    )


def get_mongo_collection():
    password = os.getenv("MONGO_PASSWORD")
    host = os.getenv("MONGO_HOST", "localhost")
    uri = f"mongodb://covid_admin:{password}@{host}:27017/?authSource=admin"
    client = MongoClient(uri)
    return client, client["covid_platform"]["annotations"]


def fetch_df(conn, query, params=None):
    """Run a query and return a clean dataframe.

    Snowflake silently closes idle sessions (~4h) - discovered when
    the dashboard showed n/a everywhere after the stack sat idle
    overnight. So: try once, and if the session is dead, rebuild the
    shared connection and retry exactly once (self-healing).
    Also does the same Decimal/date cleanup as analysis/sf_connect.py.
    """
    for attempt in (1, 2):
        try:
            cur = conn.cursor()
            cur.execute(query, params or {})
            df = cur.fetch_pandas_all()
            break
        except Exception:
            if attempt == 2:
                raise
            try:
                conn.close()
            except Exception:
                pass
            conn = get_snowflake_connection()
            app.state.sf_conn = conn  # future requests use the fresh one

    if "DATE" in df.columns:
        df["DATE"] = pd.to_datetime(df["DATE"]).dt.strftime("%Y-%m-%d")
    for col in df.columns:
        if df[col].dtype == "object" and col != "COUNTRY_REGION":
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
    return df


@lru_cache(maxsize=4)
def read_snapshot(name):
    """Load one Parquet snapshot from disk (cached for the process
    lifetime - these files never change while the API runs)."""
    path = SNAPSHOT_DIR / f"{name}.parquet"
    if not path.exists():
        raise HTTPException(
            503,
            f"Snowflake is unreachable and no snapshot found at {path}. "
            "Run analysis/export_snapshot.py while Snowflake is available.",
        )
    return pd.read_parquet(path)


def query_data(query, params, snapshot_name, snapshot_filter=None):
    """Single data-access path for every endpoint: live Snowflake when
    possible, local snapshot otherwise. A failure is not permanent -
    after SNOWFLAKE_RETRY_AFTER seconds the next request tries to
    reconnect, so a transient network problem does not pin the process
    to the snapshot until restart. `snapshot_filter` re-applies in
    pandas whatever the SQL WHERE/ORDER BY did, so both paths return
    the same frame."""
    if not FORCE_SNAPSHOT and snowflake_configured():
        if app.state.sf_conn is None and time.monotonic() >= app.state.sf_retry_at:
            try:
                app.state.sf_conn = get_snowflake_connection()
                app.state.sf_reconnects += 1
            except Exception:
                app.state.sf_retry_at = time.monotonic() + SNOWFLAKE_RETRY_AFTER

        if app.state.sf_conn is not None:
            try:
                df = fetch_df(app.state.sf_conn, query, params)
                app.state.data_source = "snowflake"
                return df
            except Exception:
                app.state.sf_conn = None
                app.state.sf_failures += 1
                app.state.sf_retry_at = time.monotonic() + SNOWFLAKE_RETRY_AFTER

    app.state.data_source = "snapshot"
    df = read_snapshot(snapshot_name).copy()
    return snapshot_filter(df) if snapshot_filter else df


def load_enriched():
    """COUNTRY_ENRICHED, whole table."""
    return query_data(
        "SELECT * FROM COVID_PROJECT.ANALYTICS.COUNTRY_ENRICHED",
        None, "country_enriched",
    )


def load_daily(country):
    """JHU_DAILY_COUNTRY for one country, ordered by date."""
    return query_data(
        """
        SELECT DATE, COUNTRY_REGION, CUM_CONFIRMED, CUM_DEATHS
        FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
        WHERE COUNTRY_REGION = %(country)s
        ORDER BY DATE
        """,
        {"country": country}, "jhu_daily_country",
        snapshot_filter=lambda d: (
            d[d["COUNTRY_REGION"] == country].sort_values("DATE").reset_index(drop=True)
        ),
    )

def load_all_daily():
    """JHU_DAILY_COUNTRY, every country - used for the world totals."""
    return query_data(
        """
        SELECT DATE, COUNTRY_REGION, CUM_CONFIRMED, CUM_DEATHS
        FROM COVID_PROJECT.ANALYTICS.JHU_DAILY_COUNTRY
        ORDER BY COUNTRY_REGION, DATE
        """,
        None, "jhu_daily_country",
        snapshot_filter=lambda d: d.sort_values(["COUNTRY_REGION", "DATE"]),
    )





def to_json_safe(df):
    """NaN is not valid JSON (FastAPI's encoder rejects it), so every
    NaN becomes a real None -> serialized as null. Needed because some
    enrichment fields (e.g. literacy) are missing for a few countries -
    the exact data gap documented back in Task 2."""
    return df.replace({np.nan: None})


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A failed Snowflake connection must not stop the API from
    # starting - it just means every request is served from the
    # snapshot instead.
    app.state.data_source = "unknown"
    app.state.sf_retry_at = 0.0
    app.state.sf_failures = 0
    app.state.sf_reconnects = 0
    if FORCE_SNAPSHOT or not snowflake_configured():
        app.state.sf_conn = None
    else:
        try:
            app.state.sf_conn = get_snowflake_connection()
        except Exception:
            app.state.sf_conn = None
    app.state.mongo_client, app.state.annotations = get_mongo_collection()
    yield
    if app.state.sf_conn is not None:
        app.state.sf_conn.close()
    app.state.mongo_client.close()


# --- Task 8: caching layer -----------------------------------------
# The COVID dataset is frozen (JHU stopped updating in March 2023),
# so identical requests always produce identical answers. Query
# results are therefore kept in an in-process TTL cache: up to 256
# entries, each valid for 10 minutes. A TTL (instead of caching
# forever) keeps the pattern correct even for data that DOES change,
# and maxsize caps memory. Annotations are deliberately NOT cached -
# users expect a comment they just posted to appear immediately.
query_cache = TTLCache(maxsize=256, ttl=600)
CACHE_STATS = {"hits": 0, "misses": 0}


def cached_fetch(key, producer):
    """Return cached result for `key`, or run `producer()` once and
    store it. Also counts hits/misses so /cache/stats can report
    how well the cache is doing."""
    if key in query_cache:
        CACHE_STATS["hits"] += 1
        return query_cache[key]
    CACHE_STATS["misses"] += 1
    result = producer()
    query_cache[key] = result
    return result


app = FastAPI(
    title="COVID-19 Data Platform API",
    description=(
        "Serves COVID-19 case/death data from Snowflake (enriched "
        "with demographic data), plus user annotations from MongoDB. "
        "Falls back to a bundled Parquet snapshot when Snowflake is "
        "unreachable."
    ),
    version="1.1.0",
    lifespan=lifespan,
)


class Annotation(BaseModel):
    """Length caps keep a public write endpoint from accepting
    unbounded strings; without them a single request could store an
    arbitrarily large document."""
    country: str = Field(max_length=100)
    date: str = Field(max_length=10)
    metric: str = Field(max_length=50)
    comment: str = Field(min_length=1, max_length=2000)
    author: str = Field(min_length=1, max_length=100)
    email: EmailStr
    tags: list[str] = Field(default_factory=list, max_length=10)
    source_url: Optional[str] = Field(default=None, max_length=500)


@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs", "data_source": app.state.data_source}


@app.get("/health")
def health():
    """Shows which data path is live - useful for demoing that the
    platform keeps serving after the Snowflake trial expires."""
    return {
        "snowflake_connected": app.state.sf_conn is not None,
        "force_snapshot": FORCE_SNAPSHOT,
        "snowflake_configured": snowflake_configured(),
        "last_data_source": app.state.data_source,
        "snowflake_failures": app.state.sf_failures,
        "snowflake_reconnects": app.state.sf_reconnects,
        "snapshot_dir": str(SNAPSHOT_DIR),
        "snapshot_files_present": sorted(
            p.name for p in SNAPSHOT_DIR.glob("*.parquet")
        ) if SNAPSHOT_DIR.exists() else [],
    }


@app.get("/cache/stats")
def cache_stats():
    """Task 8 observability: live hit/miss counts and current size."""
    total = CACHE_STATS["hits"] + CACHE_STATS["misses"]
    hit_rate = CACHE_STATS["hits"] / total if total else 0.0
    return {
        "hits": CACHE_STATS["hits"],
        "misses": CACHE_STATS["misses"],
        "hit_rate": round(hit_rate, 3),
        "entries_in_cache": len(query_cache),
        "maxsize": query_cache.maxsize,
        "ttl_seconds": query_cache.ttl,
    }


@app.get("/countries")
def list_countries():
    """All countries available in the enriched table. Cached - Task 8."""
    def produce():
        df = load_enriched()
        return sorted(df["COUNTRY_REGION"].tolist())

    return cached_fetch(("countries",), produce)


@app.get("/enriched")
def all_enriched():
    """All rows of the enriched table at once - used by the
    dashboard's cross-country comparison chart, so it doesn't have
    to call /covid/{country}/summary once per country."""
    return to_json_safe(load_enriched()).to_dict(orient="records")


@app.get("/covid/{country}")
def covid_timeseries(
    country: str,
    rolling: int = Query(1, ge=1, le=30,
                         description="Rolling-average window in days"),
):
    
    """Daily new cases/deaths for one country, computed on the fly
    from cumulative numbers. Cached per (country, rolling) pair -
    Task 8."""
    def produce():
        df = load_daily(country)
        if df.empty:
            raise HTTPException(404, f"No data found for country '{country}'")

        # Reporting corrections occasionally make cumulative totals
        # dip (a country revises an earlier count down), which would
        # show up as negative "new cases" - a data artifact, not a
        # real decrease (same issue documented in Task 2's SQL
        # exploration, already fixed the same way in Task 6's
        # forecast.py). Clipped to 0 right after computing the diff,
        # unconditionally, before anything downstream reads these
        # columns.
        df["NEW_CONFIRMED"] = df["CUM_CONFIRMED"].diff().clip(lower=0)
        df["NEW_DEATHS"] = df["CUM_DEATHS"].diff().clip(lower=0)

        if rolling > 1:
            # min_periods=1 so the first days of the series show a
            # partial average instead of NaN (which fillna would then
            # turn into a misleading zero). Matches /global and
            # /forecast, which already do this.
            df["NEW_CONFIRMED"] = df["NEW_CONFIRMED"].rolling(rolling, min_periods=1).mean()
            df["NEW_DEATHS"] = df["NEW_DEATHS"].rolling(rolling, min_periods=1).mean()

        keep = ["DATE", "CUM_CONFIRMED", "CUM_DEATHS", "NEW_CONFIRMED", "NEW_DEATHS"]
        return df[keep].fillna(0).to_dict(orient="records")

    return cached_fetch(("timeseries", country, rolling), produce)


@app.get("/covid/{country}/summary")
def covid_summary(country: str):
    """Latest totals + demographic enrichment for one country.
    Cached per country - Task 8."""
    def produce():
        df = load_enriched()
        row = df[df["COUNTRY_REGION"] == country]
        if row.empty:
            raise HTTPException(404, f"No enriched data for country '{country}'")
        return to_json_safe(row).iloc[0].to_dict()

    return cached_fetch(("summary", country), produce)


@app.get("/forecast/{country}")
def forecast_country(
    country: str,
    horizon: int = Query(30, ge=1, le=90,
                         description="Days to forecast beyond the data"),
    test: int = Query(30, ge=7, le=90,
                      description="Days held out to validate the model"),
):
    """Task 6: Holt-Winters forecast of daily new cases for one
    country, computed live. Trailing zeros (reporting stopped) are
    trimmed so the model isn't judged on non-reporting days. Cached
    per (country, horizon, test)."""
    def produce():
        df = load_daily(country)
        if df.empty:
            raise HTTPException(404, f"No data for country '{country}'")

        s = df.set_index(pd.to_datetime(df["DATE"]))["CUM_CONFIRMED"]
        s = s.asfreq("D").diff().clip(lower=0).fillna(0)

        # trim trailing zeros (reporting stopped, not zero cases)
        nonzero = s[s > 0]
        if len(nonzero) < 60:
            raise HTTPException(422, f"Not enough reported data for '{country}'")
        s = s.loc[:nonzero.index.max()]

        # smooth a little so the weekly reporting sawtooth doesn't
        # dominate the visual
        s7 = s.rolling(7, min_periods=1).mean()

        n_test = min(test, max(14, len(s7) // 5))
        train = s7.iloc[:-n_test]
        try:
            model = ExponentialSmoothing(
                train, trend="add", seasonal="add",
                seasonal_periods=7, damped_trend=True,
            ).fit()
            test_fc = model.forecast(n_test).clip(lower=0)
            final = ExponentialSmoothing(
                s7, trend="add", seasonal="add",
                seasonal_periods=7, damped_trend=True,
            ).fit()
            future_fc = final.forecast(horizon).clip(lower=0)
        except Exception as exc:
            raise HTTPException(422, f"Model failed for '{country}': {exc}")

        actual = s7.iloc[-n_test:]
        err = actual.values - test_fc.values
        mae = float(np.abs(err).mean())
        nz = actual.values != 0
        mape = float((np.abs(err[nz]) / actual.values[nz]).mean() * 100) if nz.any() else None

        # MASE scales the error against a naive "tomorrow = today"
        # forecast on the training data. MAPE explodes at the end of
        # this dataset because daily counts fall to single digits and
        # it divides by them; MASE has no such problem, so it is the
        # metric to trust here. MASE < 1 means the model beats naive.
        naive_scale = float(np.abs(np.diff(train.values)).mean())
        mase = float(mae / naive_scale) if naive_scale > 0 else None

        def pack(series):
            return [{"DATE": d.strftime("%Y-%m-%d"), "VALUE": float(v)}
                    for d, v in series.items()]

        return {
            "country": country,
            "history": pack(s7.tail(180)),
            "test_forecast": pack(test_fc),
            "future_forecast": pack(future_fc),
            "mae": round(mae, 1),
            "mape": round(mape, 1) if mape is not None else None,
            "mase": round(mase, 2) if mase is not None else None,
        }

    return cached_fetch(("forecast", country, horizon, test), produce)


@app.get("/clusters")
def clusters():
    """Task 6 bonus: K-Means clustering of all countries by outcome +
    demographic features. Because K-Means groups on 4 standardized
    features, plotting only two of them makes the clusters look
    tangled - so PCA projects the 4D space down to 2D, which is what
    the dashboard actually plots. Raw GDP/deaths are returned too,
    for tooltips. Cached."""
    def produce():
        feats = ["GDP_PER_CAPITA", "LITERACY_PCT", "CASES_PER_100K", "DEATHS_PER_100K"]
        df = load_enriched().dropna(subset=feats).reset_index(drop=True)

        X = StandardScaler().fit_transform(df[feats])
        km = KMeans(n_clusters=4, n_init=10, random_state=42).fit(X)
        df["CLUSTER"] = km.labels_.astype(int)

        coords = PCA(n_components=2, random_state=42).fit_transform(X)
        df["PCA_X"], df["PCA_Y"] = coords[:, 0], coords[:, 1]

        return df[["COUNTRY_REGION", "GDP_PER_CAPITA", "DEATHS_PER_100K",
                   "CLUSTER", "PCA_X", "PCA_Y"]].to_dict(orient="records")

    return cached_fetch(("clusters",), produce)



@app.get("/global")
def global_timeseries(
    rolling: int = Query(7, ge=1, le=30,
                         description="Rolling-average window in days"),
    country: str | None = None,
):
    """World-wide daily new cases/deaths, summed across every country.

    Daily numbers are differenced per country FIRST and only then
    summed for the incidence chart, so a country entering or leaving
    the dataset does not create a phantom global spike.

    Totals are calculated separately, from each country's latest
    cumulative figure - NOT by summing the clipped daily differences
    above. Summing the clipped differences would silently miss two
    things: each country's first reported day (diff() has no prior
    row to subtract there) and any downward revision (clipped to
    zero for the chart, but still present in the true cumulative
    count). If `country` is given, its share of the world total is
    computed the same way and returned alongside.
    """
    def produce():
        df = load_all_daily()
        df = df.sort_values(["COUNTRY_REGION", "DATE"])
        for src, dest in (("CUM_CONFIRMED", "NEW_CONFIRMED"),
                          ("CUM_DEATHS", "NEW_DEATHS")):
            df[dest] = df.groupby("COUNTRY_REGION")[src].diff().clip(lower=0)

        world = (df.groupby("DATE")[["NEW_CONFIRMED", "NEW_DEATHS"]]
                   .sum().reset_index())
        if rolling > 1:
            for c in ("NEW_CONFIRMED", "NEW_DEATHS"):
                world[c] = world[c].rolling(rolling, min_periods=1).mean()

        # Totals: each country's LATEST cumulative row, summed - this
        # is the true world total, independent of the clipped daily
        # differences used for the chart above.
        latest = df.sort_values("DATE").groupby("COUNTRY_REGION").tail(1)
        world_total_cases = float(latest["CUM_CONFIRMED"].sum())
        world_total_deaths = float(latest["CUM_DEATHS"].sum())

        totals = {
            "world_total_cases": world_total_cases,
            "world_total_deaths": world_total_deaths,
            "countries_counted": int(df["COUNTRY_REGION"].nunique()),
        }

        share = None
        if country:
            sub = latest[latest["COUNTRY_REGION"] == country]
            if not sub.empty and world_total_cases > 0:
                share = {
                    "country": country,
                    "cases_share_pct": round(
                        float(sub["CUM_CONFIRMED"].iloc[0]) / world_total_cases * 100, 2),
                    "deaths_share_pct": round(
                        float(sub["CUM_DEATHS"].iloc[0]) / world_total_deaths * 100, 2),
                }

        return {
            "series": world.fillna(0).to_dict(orient="records"),
            "totals": totals,
            "share": share,
        }

    return cached_fetch(("global", rolling, country), produce)


@app.get("/annotations/{country}")
def get_annotations(country: str):
    """User annotations for a country, stored in MongoDB. The email
    is captured at submission time for accountability (Task 3/5
    bonus: gate who can comment) but is intentionally excluded from
    the public read - never shown to other visitors."""
    docs = list(app.state.annotations.find({"country": country}, {"_id": 0, "email": 0}))
    return docs


@app.post("/annotations")
def add_annotation(annotation: Annotation):
    """Add a new annotation (Task 5 bonus: user comments stored in
    the NoSQL DB)."""
    doc = annotation.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    app.state.annotations.insert_one(doc)
    return {"status": "inserted"}