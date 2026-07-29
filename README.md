# COVID-19 Data Integration, Analysis & Visualization Platform

Bootcamp final project — **Sennur Bascetin**

An end-to-end data platform built on the Snowflake Marketplace
"COVID-19 Epidemiological Data" dataset: SQL exploration, enrichment
with two external datasets, a NoSQL annotation store, a FastAPI
service layer with caching, an interactive Dash dashboard, live
time-series forecasting, clustering, and SQL pattern recognition ,
deployable on any machine with Docker, and able to keep serving even
without a Snowflake account.


## Architecture

```
Browser
  |
  +--> Dash dashboard (:8050)
         |
         +--> FastAPI (:8000)
                |
                +--> Snowflake ......... COVID data + enriched tables
                +--> Parquet snapshot ... automatic fallback
                +--> MongoDB (:27017) ... user annotations
```

Three containers orchestrated by Docker Compose: `dashboard`, `api`,
`mongo`. The dashboard only ever talks to the API — the API is the
single data-access layer.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Cases / deaths | JHU, via Snowflake Marketplace | daily, country level, ends 2023-03-09 |
| Population, ISO code, region | ECDC, via Snowflake Marketplace | 2019 figures, contemporary with the pandemic |
| GDP, median age, vaccination, excess mortality | Our World in Data | external dataset |
| Literacy | Kaggle "Countries of the World" | external dataset (~2006 figures) |

Population deliberately comes from ECDC rather than Kaggle: Kaggle's
file is a ~2006 CIA World Factbook snapshot, and using it as the
denominator distorted every per-capita rate. GDP was moved to OWID for
the same reason (Qatar: $21,500 in Kaggle vs $110,890 in OWID).

## Prerequisites

- Docker with the Compose plugin (`docker compose version` to check)
- Optional: a Snowflake account (free trial) on **AWS, Stockholm
  (eu-north-1)** with the free Marketplace dataset **"COVID-19
  Epidemiological Data"** (Starschema) installed as
  `COVID19_EPIDEMIOLOGICAL_DATA`

Snowflake is optional because the repository ships a Parquet snapshot
of the two tables the API reads. Without Snowflake credentials the API
serves that snapshot automatically and the dashboard behaves
identically.

## Quick start (no Snowflake needed)

```bash
git clone https://github.com/sennurbascetin/covid-platform.git 
cd covid-platform
cp .env.example .env          # set MONGO_PASSWORD; Snowflake fields can stay blank
docker compose up -d --build
```

Then open:
- Dashboard: http://localhost:8050
- API docs: http://localhost:8000/docs
- Which data path is live: http://localhost:8000/health

To seed the sample MongoDB annotations (optional):

```bash
python3 -m venv venv && source venv/bin/activate
pip install pymongo python-dotenv
python analysis/setup_mongo_schema.py
```

## Full setup with your own Snowflake account

1. **Create a key pair** (Snowflake no longer allows password auth for
   programmatic access):

       mkdir -p secrets && cd secrets
       openssl genrsa -out rsa_key.pem 2048
       openssl pkcs8 -topk8 -inform PEM -in rsa_key.pem -out rsa_key.p8 -nocrypt
       openssl rsa -in rsa_key.pem -pubout -out rsa_key.pub
       chmod 600 rsa_key.pem rsa_key.p8
       grep -v "BEGIN PUBLIC KEY\|END PUBLIC KEY" rsa_key.pub | tr -d '\n'; echo
       cd ..

   Copy the printed key, then in a Snowflake worksheet:

       ALTER USER <YOUR_USER> SET RSA_PUBLIC_KEY='<PASTE_KEY_HERE>';

2. **Configure** — `cp .env.example .env` and fill in
   `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `MONGO_PASSWORD`.

3. **Run the SQL scripts once**, in order, in a Snowflake worksheet:

   | File | Creates |
   |---|---|
   | `sql/01_setup_resource_monitor.sql` | resource monitor (Task 1) |
   | `sql/02_exploration.sql` | exploration queries (Task 2a) |
   | `sql/03_create_database.sql` | `COVID_PROJECT.ANALYTICS` database + schema |
   | `sql/04_optimization.sql` | pre-aggregated `JHU_DAILY_COUNTRY` (Task 7) |
   | `sql/05_country_base.sql` | `COUNTRY_BASE` (population, ISO, per-100k rates) |
   | `sql/06_pattern_recognition.sql` | MATCH_RECOGNIZE wave detection (Task 9) |
   | `sql/07_data_quality_checks.sql` | population / ISO-code verification |

4. **Build the enriched table** (Python needed for this step only):

       python3 -m venv venv && source venv/bin/activate
       pip install "snowflake-connector-python[pandas]" python-dotenv pandas \
                   pymongo matplotlib statsmodels scikit-learn pycountry pyarrow

       python analysis/enrich_data.py    # adds literacy from Kaggle
       python analysis/enrich_owid.py    # adds GDP, age, vaccination, excess mortality
       python analysis/export_snapshot.py  # refresh the offline snapshot

   `data/owid_country_static.csv` (one row per country, 31 KB) is
   committed, so step 4 works from a fresh clone. To regenerate it from
   scratch, download OWID's full export from
   `https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv`
   to `data/owid_covid.csv` and run `python analysis/distill_owid.py`.
   The full export (170 MB) is git-ignored.

5. **Launch** — `docker compose up -d --build`

**Important:** any time the enrichment scripts change the data, re-run
`export_snapshot.py` so the offline fallback stays in sync.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /countries` | country list |
| `GET /enriched` | full enriched table |
| `GET /covid/{country}?rolling=7` | daily new cases/deaths, differenced on the fly |
| `GET /covid/{country}/summary` | latest totals + all enrichment fields |
| `GET /global?rolling=7&country=X` | world totals + one country's share |
| `GET /forecast/{country}` | live Holt-Winters forecast + MASE/MAPE/MAE |
| `GET /clusters` | K-Means clusters, PCA-projected to 2D |
| `GET /annotations/{country}` · `POST /annotations` | MongoDB annotations |
| `GET /cache/stats` | cache hit/miss counters (Task 8) |
| `GET /health` | which data path is live (Snowflake or snapshot) |

## Repository layout

    api/          FastAPI service (Snowflake + snapshot + MongoDB + TTL cache)
    dashboard/    Dash web app (talks only to the API)
    analysis/     Offline scripts: automated EDA, enrichment, forecasting,
                  clustering, snapshot export
    sql/          Snowflake worksheets (setup, exploration, optimization,
                  MATCH_RECOGNIZE patterns, data-quality checks)
    data/         External datasets + the Parquet snapshot
    secrets/      Snowflake private key (git-ignored, never committed)

## Key design decisions

- **Offline fallback.** The API prefers live Snowflake and silently
  serves a committed Parquet snapshot when it is unreachable, so the
  platform survives an expired trial or a reviewer without credentials.
  Set `FORCE_SNAPSHOT=1` on the api service to exercise that path
  deliberately; `/health` reports which source answered.
- **Key-pair auth, secrets outside the image.** The Snowflake key is
  mounted read-only into the API container; nothing sensitive is baked
  into images or committed.
- **Pre-aggregation in Snowflake (Task 7).** The API reads a
  once-computed country/day summary table instead of re-aggregating the
  raw multi-million-row JHU table per request.
- **In-process TTL cache (Task 8).** The dataset is frozen, so
  identical requests are served from memory; `/cache/stats` exposes
  live counters. Redis was deliberately not used — one API instance,
  static data.
- **Self-healing Snowflake session.** Snowflake closes idle sessions
  after a few hours; the API detects a dead session and reconnects
  transparently instead of degrading to errors.
- **Same code, two environments.** Connection targets come from
  environment variables, so the code runs unchanged locally and inside
  Compose (`MONGO_HOST=mongo`, `API_URL=http://api:8000`).

## Known limitations

- The JHU dataset ends 2023-03-09; "forecast" means the days after the
  last reported date, not the present day.
- Excess mortality is available for roughly 114 of 198 countries — it
  requires reliable pre-pandemic death registration, which biases the
  sample toward wealthier countries.
- Literacy still comes from the ~2006 Kaggle file; OWID does not carry
  it and the marketplace dataset has no equivalent.
- 18 JHU entries have no population match: cruise ships and Olympics
  categories (not countries), French overseas regions counted under
  France, North Korea, and small Pacific states outside ECDC coverage.
- Country-level correlations in the dashboard are ecological: they
  describe populations, not individuals, and are reported with an
  age-adjusted figure alongside the raw one for that reason.