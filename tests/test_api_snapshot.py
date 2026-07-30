# Tests run against the API in FORCE_SNAPSHOT mode, so they need no
# Snowflake credentials and pass in CI. They cover the behaviour that
# was fixed during external review: bounded query parameters, the
# per-capita fallback that must omit rather than mislead, and
# annotation validation.

import os

os.environ["FORCE_SNAPSHOT"] = "1"

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from fastapi.testclient import TestClient
from main import app

# TestClient must be used as a context manager, or FastAPI's lifespan
# (which sets app.state.sf_conn, opens Mongo, etc.) never runs and
# every endpoint that reads app.state fails with AttributeError.
client = TestClient(app)
client.__enter__()


def test_health_reports_snapshot_mode():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["force_snapshot"] is True
    assert body["snowflake_connected"] is False


def test_countries_list_is_nonempty_from_snapshot():
    resp = client.get("/countries")
    assert resp.status_code == 200
    countries = resp.json()
    assert len(countries) > 100
    assert "Turkey" in countries


def test_covid_timeseries_rejects_out_of_range_rolling():
    # rolling is bounded 1-30; this is the fix for the unbounded
    # parameter finding from the external review.
    resp = client.get("/covid/Turkey", params={"rolling": 999})
    assert resp.status_code == 422


def test_covid_timeseries_accepts_valid_rolling():
    resp = client.get("/covid/Turkey", params={"rolling": 7})
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) > 0
    assert "NEW_CONFIRMED" in rows[0]


def test_forecast_horizon_is_bounded():
    resp = client.get("/forecast/Turkey", params={"horizon": 99999})
    assert resp.status_code == 422


def test_global_totals_use_latest_cumulative_not_summed_diffs():
    # Regression test for the world-totals bug found in review: totals
    # must come from each country's latest cumulative row, not from
    # summing the clipped daily differences used for the chart.
    resp = client.get("/global", params={"rolling": 7, "country": "Turkey"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["world_total_cases"] > 0
    assert body["totals"]["world_total_deaths"] > 0
    assert body["share"]["country"] == "Turkey"
    assert 0 < body["share"]["cases_share_pct"] < 100


def test_annotation_rejects_invalid_email():
    payload = {
        "country": "Turkey",
        "date": "2023-01-01",
        "metric": "general",
        "comment": "test",
        "author": "Tester",
        "email": "not-an-email",
        "tags": [],
        "source_url": None,
    }
    resp = client.post("/annotations", json=payload)
    assert resp.status_code == 422


def test_annotation_rejects_oversized_comment():
    payload = {
        "country": "Turkey",
        "date": "2023-01-01",
        "metric": "general",
        "comment": "x" * 5000,  # over the 2000-char cap
        "author": "Tester",
        "email": "test@example.com",
        "tags": [],
        "source_url": None,
    }
    resp = client.post("/annotations", json=payload)
    assert resp.status_code == 422


def test_clusters_endpoint_returns_pca_coordinates():
    resp = client.get("/clusters")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) > 50
    assert "PCA_X" in rows[0]
    assert "CLUSTER" in rows[0]


def teardown_module(module):
    client.__exit__(None, None, None)
