# Task 5: Interactive Visualization (+ Task 4 on-the-fly processing:
# case-fatality ratio and the partial correlation below are both
# computed here, at request time).
# Dash dashboard that talks ONLY to the FastAPI service (never
# straight to Snowflake or MongoDB) - the API is the single access
# layer, the dashboard is purely presentation.
#
# Two-country comparison: "Country A" and "Country B" (B optional).
# Colors are assigned by SLOT, not by specific country identity - any
# two countries chosen get the same strong, easy-to-tell-apart red vs
# blue pair. Defaults to Turkey (A) vs Latvia (B).
#
# Charts: daily cases/deaths, regional breakdown, GDP vs deaths,
# live Holt-Winters forecast for both countries, K-Means clusters
# (PCA-projected), and a vaccination vs excess-mortality view that
# deliberately shows both the raw and the age-adjusted correlation.
#
# Annotations (Task 3/5 bonus): the commenter picks WHICH of the two
# selected countries the note is about, and must supply a valid email
# to submit - checked both here (fast feedback) and again by the API
# itself via Pydantic's EmailStr (so the gate holds even if someone
# calls the API directly, bypassing this UI).

import os
import time
import re

import dash
import pandas as pd
import plotly.graph_objects as go
import requests
from dash import Input, Output, State, ctx, dcc, html

API_URL = os.getenv("API_URL", "http://localhost:8000")

COUNTRY_A_COLOR = "#E30A17"  # crimson - Turkey by default
COUNTRY_B_COLOR = "#1B6CA8"  # strong blue - Latvia by default; chosen
                              # for maximum contrast against A's red
ACCENT_BG = "#fdf6f6"
INK = "#2b2323"
MUTED = "#8a7676"
BORDER = "#f0dcdc"

# Forecast chart colors (Task 6, computed live per selected country).
# Country A gets the deep shades, Country B the lighter version of the
# same three roles, so both fit one chart without confusion.
FORECAST_HISTORY = "#6C3FA6"   # purple  - actual history
FORECAST_TEST = "#1B7A3D"      # dark green (dashed) - back-test forecast
FORECAST_FUTURE = "#C2185B"    # dark pink - forecast beyond the data
FORECAST_HISTORY_B = "#A98BD1"  # light purple
FORECAST_TEST_B = "#5FA87A"     # light green (dashed)
FORECAST_FUTURE_B = "#E77FA8"   # light pink

CLUSTER_PALETTE = ["#E30A17", "#1B6CA8", "#F2A900", "#2E8B57"]  # 4 clusters

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = dash.Dash(__name__)
app.title = "COVID-19 Data Platform"

SIDEBAR_STYLE = {
    "width": "320px",
    "minWidth": "320px",
    "background": ACCENT_BG,
    "padding": "24px 20px",
    "borderRight": f"3px solid {COUNTRY_A_COLOR}",
    "minHeight": "100vh",
    "boxSizing": "border-box",
}

CONTENT_STYLE = {
    "flex": "1",
    "padding": "24px 32px",
    "maxWidth": "1000px",
    "boxSizing": "border-box",
}

CARD_STYLE = {
    "background": "white",
    "border": f"1px solid {BORDER}",
    "borderLeft": f"4px solid {COUNTRY_A_COLOR}",
    "borderRadius": "8px",
    "padding": "10px 14px",
    "marginBottom": "10px",
}

ANNOTATION_STYLE = {
    "background": "white",
    "border": f"1px solid {BORDER}",
    "borderLeft": f"5px solid {COUNTRY_B_COLOR}",
    "borderRadius": "8px",
    "padding": "12px 16px",
    "marginBottom": "10px",
    "boxShadow": "0 1px 3px rgba(0,0,0,0.06)",
}


def get_countries(retries=10, delay=3):
    """Fetch the country list at startup, waiting for the API to
    become reachable. Without the retry the dropdown silently stays
    empty if the dashboard boots a moment before the API is ready -
    the same startup-timing failure I hit earlier with the enriched
    dataset."""
    for _ in range(retries):
        try:
            resp = requests.get(f"{API_URL}/countries", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data:
                return data
        except requests.RequestException:
            pass
        time.sleep(delay)
    return []


def get_all_enriched():
    try:
        resp = requests.get(f"{API_URL}/enriched", timeout=10)
        resp.raise_for_status()
        return pd.DataFrame(resp.json())
    except requests.RequestException:
        return pd.DataFrame()


def fetch_summary(country):
    if not country:
        return {}
    resp = requests.get(f"{API_URL}/covid/{country}/summary", timeout=10)
    return resp.json() if resp.ok else {}


def fetch_timeseries(country, rolling):
    if not country:
        return pd.DataFrame()
    resp = requests.get(f"{API_URL}/covid/{country}", params={"rolling": rolling}, timeout=10)
    return pd.DataFrame(resp.json()) if resp.ok else pd.DataFrame()


def fetch_forecast(country):
    """Live Holt-Winters forecast for one country (Task 6). Longer
    timeout because the model is fit on request; the API caches the
    result so repeat selections are instant."""
    if not country:
        return {}
    try:
        resp = requests.get(f"{API_URL}/forecast/{country}", timeout=30)
        return resp.json() if resp.ok else {}
    except requests.RequestException:
        return {}


def fetch_clusters():
    """K-Means clusters of all countries, already PCA-projected to 2D
    by the API (Task 6 bonus)."""
    try:
        resp = requests.get(f"{API_URL}/clusters", timeout=30)
        return pd.DataFrame(resp.json()) if resp.ok else pd.DataFrame()
    except requests.RequestException:
        return pd.DataFrame()



def fetch_global(rolling, country=None):
    """World-wide daily totals plus the selected country's share."""
    try:
        params = {"rolling": rolling}
        if country:
            params["country"] = country
        resp = requests.get(f"{API_URL}/global", params=params, timeout=30)
        return resp.json() if resp.ok else {}
    except requests.RequestException:
        return {}


    

def partial_correlation(df, x, y, z):
    """Correlation between x and y with the linear effect of z removed.

    Country-level COVID data is a textbook setting for the ecological
    fallacy: older populations were both more likely to die and more
    likely to be vaccinated early, so the raw vaccination/mortality
    correlation is confounded by age structure. Reporting the raw and
    the age-adjusted figure side by side makes that visible instead
    of hiding it.
    """
    sub = df[[x, y, z]].dropna()
    if len(sub) < 10:
        return None, None
    r_xy = sub[x].corr(sub[y])
    r_xz = sub[x].corr(sub[z])
    r_yz = sub[y].corr(sub[z])
    denom = ((1 - r_xz ** 2) * (1 - r_yz ** 2)) ** 0.5
    if denom == 0:
        return r_xy, None
    return r_xy, (r_xy - r_xz * r_yz) / denom


def metric_row(label, value_a, value_b):
    children = [html.Span(value_a, style={"color": COUNTRY_A_COLOR, "fontWeight": "700"})]
    if value_b is not None:
        children += [
            html.Span(" vs ", style={"color": MUTED, "fontSize": "11px", "margin": "0 4px"}),
            html.Span(value_b, style={"color": COUNTRY_B_COLOR, "fontWeight": "700"}),
        ]
    return html.Div([
        html.Div(children, style={"display": "flex", "alignItems": "baseline", "fontSize": "17px"}),
        html.Div(label, style={"fontSize": "11px", "color": MUTED, "textTransform": "uppercase",
                               "letterSpacing": "0.5px", "marginTop": "2px"}),
    ], style=CARD_STYLE)


def status_msg(text, is_error):
    color = "#b91c1c" if is_error else "#15803d"
    return html.Span(text, style={"color": color})


COUNTRIES = get_countries()
COUNTRY_B_OPTIONS = [{"label": "— None (single country) —", "value": ""}] + [
    {"label": c, "value": c} for c in COUNTRIES
]

app.layout = html.Div(
    style={"display": "flex", "fontFamily": "Arial, sans-serif", "background": "white"},
    children=[
        # ---------------- Sidebar ----------------
        html.Div(style=SIDEBAR_STYLE, children=[
            html.H2("COVID-19 Data Platform",
                    style={"margin": "0 0 4px 0", "color": INK, "fontSize": "22px"}),
            html.P("Accenture Baltics Data Engineering Bootcamp",
                   style={"margin": "0", "fontSize": "12px", "color": MUTED}),
            html.P("Sennur Bascetin",
                   style={"margin": "2px 0 0 0", "fontSize": "13px",
                          "fontWeight": "600", "color": COUNTRY_B_COLOR}),
            html.Hr(style={"border": f"1px solid {BORDER}", "margin": "16px 0"}),

            html.Label("Country A", style={"fontSize": "13px", "fontWeight": "600", "color": INK}),
            dcc.Dropdown(
                id="country-a-dropdown",
                options=[{"label": c, "value": c} for c in COUNTRIES],
                value="Turkey" if "Turkey" in COUNTRIES else (COUNTRIES[0] if COUNTRIES else None),
                clearable=False,
            ),
            html.Label("Country B (optional)", style={"fontSize": "13px", "fontWeight": "600",
                                                       "color": INK, "marginTop": "10px",
                                                       "display": "block"}),
            dcc.Dropdown(
                id="country-b-dropdown",
                options=COUNTRY_B_OPTIONS,
                value="Latvia" if "Latvia" in COUNTRIES else "",
                clearable=False,
            ),
            html.Div(style={"display": "flex", "gap": "14px", "margin": "8px 0 2px 0",
                            "fontSize": "12px", "color": MUTED},
                     children=[
                html.Div([html.Span("● ", style={"color": COUNTRY_A_COLOR}), "Country A"]),
                html.Div([html.Span("● ", style={"color": COUNTRY_B_COLOR}), "Country B"]),
            ]),

            html.Label("Smoothing", style={"fontSize": "13px", "fontWeight": "600",
                                           "color": INK, "marginTop": "12px", "display": "block"}),
            dcc.Dropdown(
                id="rolling-dropdown",
                options=[
                    {"label": "Daily (no smoothing)", "value": 1},
                    {"label": "7-day average", "value": 7},
                    {"label": "14-day average", "value": 14},
                ],
                value=7,
                clearable=False,
            ),

            html.Hr(style={"border": f"1px solid {BORDER}", "margin": "16px 0"}),
            html.Div(id="summary-cards"),
        ]),

        # ---------------- Main column ----------------
        html.Div(style=CONTENT_STYLE, children=[
            html.H3("World overview",
                    style={"color": INK, "borderLeft": f"6px solid {FORECAST_HISTORY}",
                           "paddingLeft": "10px", "marginTop": "0"}),
            html.P("Global daily new cases and deaths, summed across every "
                   "country in the dataset. Country A's share of the world "
                   "total is computed on the fly and shown in the title.",
                   style={"color": MUTED, "fontSize": "13px"}),
            dcc.Graph(id="global-chart"),
            html.Hr(style={"border": f"1px solid {BORDER}", "margin": "24px 0"}), 
            dcc.Graph(id="cases-chart"),
            dcc.Graph(id="deaths-chart"),

            html.H3("Regional breakdown",
                    style={"color": INK, "borderLeft": f"6px solid {COUNTRY_A_COLOR}",
                           "paddingLeft": "10px"}),
            html.P("Average COVID deaths per 100k, grouped by world region "
                   "(demographic breakdown, per the assignment brief).",
                   style={"color": MUTED, "fontSize": "13px"}),
            dcc.Graph(id="region-chart"),

            html.H3("GDP per capita vs. COVID deaths per 100,000",
                    style={"color": INK, "borderLeft": f"6px solid {COUNTRY_A_COLOR}",
                           "paddingLeft": "10px"}),
            html.P("Every dot is one country; Country A and B are highlighted. "
                   "GDP figures come from Our World in Data.",
                   style={"color": MUTED, "fontSize": "13px"}),
            dcc.Graph(id="scatter-chart"),

            html.H3("Vaccination vs. excess mortality",
                    style={"color": INK, "borderLeft": f"6px solid {FORECAST_TEST}",
                           "paddingLeft": "10px", "marginTop": "24px"}),
            html.P("Excess mortality counts deaths above the pre-pandemic "
                   "baseline, so it does not depend on how a country classified "
                   "a death as COVID. Dot colour is median age - the strongest "
                   "confounder here, since older populations were both more at "
                   "risk and vaccinated earlier. The title reports the raw "
                   "correlation and the same correlation after removing the "
                   "linear effect of age.",
                   style={"color": MUTED, "fontSize": "13px"}),
            dcc.Graph(id="vaccination-chart"),

            html.H3("Case forecast (Holt-Winters)",
                    style={"color": INK, "borderLeft": f"6px solid {FORECAST_FUTURE}",
                           "paddingLeft": "10px", "marginTop": "24px"}),
            html.P("Daily new cases for both selected countries: recent history, "
                   "a back-test on held-out days to check accuracy, and a forecast "
                   "beyond the last reported date. Country A uses the deep shades "
                   "and the left axis, Country B the lighter shades and the right "
                   "axis - two countries can differ by an order of magnitude, and "
                   "on a shared axis the smaller one collapses into a flat line."" MASE compares the model against a naive "
                   "'tomorrow = today' forecast (below 1 means the model wins); "
                   "MAPE is also shown but inflates at the end of the series, "
                   "where daily counts fall to single digits.",
                   style={"color": MUTED, "fontSize": "13px"}),
            dcc.Graph(id="forecast-chart"),

            html.H3("Country clusters (K-Means)",
                    style={"color": INK, "borderLeft": f"6px solid {FORECAST_HISTORY}",
                           "paddingLeft": "10px", "marginTop": "24px"}),
            html.P("Countries grouped into 4 clusters by GDP, literacy, and "
                   "case/death rates. The 4 features are projected to 2D with PCA "
                   "so the groups separate visually; axes are principal components, "
                   "not raw units. Country A (and B) are marked with a star.",
                   style={"color": MUTED, "fontSize": "13px"}),
            dcc.Graph(id="cluster-chart"),

            html.Hr(style={"border": f"1px solid {BORDER}", "margin": "24px 0"}),
            html.H3("Annotations",
                    style={"color": INK, "borderLeft": f"6px solid {COUNTRY_B_COLOR}",
                           "paddingLeft": "10px"}),
            html.P("Community notes on specific data points - stored in MongoDB. "
                   "Author name is shown; email is required to post but never displayed.",
                   style={"color": MUTED, "fontSize": "13px"}),
            html.Div(id="annotations-list"),

            html.Div(style={"background": ACCENT_BG, "padding": "16px",
                            "borderRadius": "8px", "marginTop": "16px"},
                     children=[
                html.H4("Add an annotation", style={"margin": "0 0 10px 0", "color": INK}),

                html.Label("Which country is this about?",
                           style={"fontSize": "12px", "color": MUTED, "display": "block",
                                  "marginBottom": "4px"}),
                dcc.Dropdown(id="annotation-target-dropdown", clearable=False,
                            style={"marginBottom": "10px"}),

                dcc.Textarea(
                    id="new-comment", placeholder="Your comment...",
                    style={"width": "100%", "height": "80px", "boxSizing": "border-box",
                           "border": f"1px solid {BORDER}", "borderRadius": "6px",
                           "padding": "8px", "fontFamily": "inherit"},
                ),
                html.Div(style={"display": "flex", "gap": "8px", "marginTop": "10px",
                                "flexWrap": "wrap"},
                         children=[
                    dcc.Input(id="new-author", type="text", placeholder="Your name",
                              value="Sennur Bascetin",
                              style={"flex": "1", "minWidth": "150px", "border": f"1px solid {BORDER}",
                                     "borderRadius": "6px", "padding": "8px"}),
                    dcc.Input(id="new-email", type="email", placeholder="Your email",
                              style={"flex": "1", "minWidth": "150px", "border": f"1px solid {BORDER}",
                                     "borderRadius": "6px", "padding": "8px"}),
                    html.Button("Submit", id="submit-annotation", n_clicks=0,
                                style={"background": COUNTRY_A_COLOR, "color": "white",
                                       "border": "none", "padding": "8px 24px",
                                       "borderRadius": "6px", "cursor": "pointer",
                                       "fontWeight": "600"}),
                ]),
                html.Div(id="annotation-form-status",
                         style={"fontSize": "12px", "marginTop": "8px", "minHeight": "16px"}),
            ]),
        ]),
    ],
)


@app.callback(
    Output("annotation-target-dropdown", "options"),
    Output("annotation-target-dropdown", "value"),
    Input("country-a-dropdown", "value"),
    Input("country-b-dropdown", "value"),
)
def update_annotation_target(country_a, country_b):
    """Keeps the 'which country is this about?' dropdown in sync
    with whatever A/B are currently selected, so the commenter is
    never able to post to a country that isn't even on screen."""
    options = [{"label": f"{country_a} (Country A)", "value": country_a}]
    if country_b:
        options.append({"label": f"{country_b} (Country B)", "value": country_b})
    return options, country_a


@app.callback(
    Output("summary-cards", "children"),
    Output("global-chart", "figure"),
    Output("cases-chart", "figure"),
    Output("deaths-chart", "figure"),
    Output("region-chart", "figure"),
    Output("scatter-chart", "figure"),
    Output("vaccination-chart", "figure"),
    Output("forecast-chart", "figure"),
    Output("cluster-chart", "figure"),
    Input("country-a-dropdown", "value"),
    Input("country-b-dropdown", "value"),
    Input("rolling-dropdown", "value"),
)
def update_view(country_a, country_b, rolling):
    country_b = country_b or None

    if not country_a:
        return ([], go.Figure(), go.Figure(), go.Figure(), go.Figure(),
                go.Figure(), go.Figure(), go.Figure(), go.Figure())

    summary_a = fetch_summary(country_a)
    summary_b = fetch_summary(country_b) if country_b else {}

    def mv(summary, key, fmt):
        value = summary.get(key)
        return fmt.format(value) if value is not None else "n/a"

    def cfr(summary):
        c, d = summary.get("CUM_CONFIRMED"), summary.get("CUM_DEATHS")
        return f"{d / c * 100:.1f}%" if c and d else "n/a"

    rows = [
        ("Total cases", mv(summary_a, "CUM_CONFIRMED", "{:,.0f}"),
         mv(summary_b, "CUM_CONFIRMED", "{:,.0f}") if country_b else None),
        ("Total deaths", mv(summary_a, "CUM_DEATHS", "{:,.0f}"),
         mv(summary_b, "CUM_DEATHS", "{:,.0f}") if country_b else None),
        ("Case fatality ratio", cfr(summary_a), cfr(summary_b) if country_b else None),
        ("Cases / 100k", mv(summary_a, "CASES_PER_100K", "{:,.0f}"),
         mv(summary_b, "CASES_PER_100K", "{:,.0f}") if country_b else None),
        ("Deaths / 100k", mv(summary_a, "DEATHS_PER_100K", "{:,.1f}"),
         mv(summary_b, "DEATHS_PER_100K", "{:,.1f}") if country_b else None),
        ("Excess deaths / million", mv(summary_a, "EXCESS_DEATHS_PER_MILLION", "{:,.0f}"),
         mv(summary_b, "EXCESS_DEATHS_PER_MILLION", "{:,.0f}") if country_b else None),
        ("Vaccinated", mv(summary_a, "VACCINATED_PCT", "{:.1f}%"),
         mv(summary_b, "VACCINATED_PCT", "{:.1f}%") if country_b else None),
        ("Median age", mv(summary_a, "MEDIAN_AGE", "{:.1f}"),
         mv(summary_b, "MEDIAN_AGE", "{:.1f}") if country_b else None),
        ("Population", mv(summary_a, "POPULATION", "{:,.0f}"),
         mv(summary_b, "POPULATION", "{:,.0f}") if country_b else None),
        ("GDP per capita", mv(summary_a, "GDP_PER_CAPITA", "${:,.0f}"),
         mv(summary_b, "GDP_PER_CAPITA", "${:,.0f}") if country_b else None),
        ("Literacy", mv(summary_a, "LITERACY_PCT", "{:.1f}%"),
         mv(summary_b, "LITERACY_PCT", "{:.1f}%") if country_b else None),
        ("Data through", str(summary_a.get("DATE") or "n/a")[:10],
         str(summary_b.get("DATE") or "n/a")[:10] if country_b else None),
    ]
    cards = [metric_row(label, va, vb) for label, va, vb in rows]

    ts_a = fetch_timeseries(country_a, rolling)
    ts_b = fetch_timeseries(country_b, rolling) if country_b else pd.DataFrame()
    title_suffix = f"{country_a} vs {country_b}" if country_b else country_a


# --- World overview (Task 5: global infection/mortality metrics) ---
    global_fig = go.Figure()
    gl = fetch_global(rolling, country_a)
    if gl and gl.get("series"):
        gdf = pd.DataFrame(gl["series"])
        global_fig.add_trace(go.Scatter(
            x=gdf["DATE"], y=gdf["NEW_CONFIRMED"], mode="lines",
            name="World - new cases", line=dict(color=FORECAST_HISTORY, width=2)))
        global_fig.add_trace(go.Scatter(
            x=gdf["DATE"], y=gdf["NEW_DEATHS"], mode="lines", yaxis="y2",
            name="World - deaths", line=dict(color=FORECAST_FUTURE, width=2)))

        t = gl.get("totals", {})
        bits = [f"{t.get('countries_counted', 0)} countries",
                f"{t.get('world_total_cases', 0):,.0f} total cases",
                f"{t.get('world_total_deaths', 0):,.0f} total deaths"]
        sh = gl.get("share")
        if sh:
            bits.append(f"{sh['country']}: {sh['cases_share_pct']}% of cases, "
                        f"{sh['deaths_share_pct']}% of deaths")
        global_fig.update_layout(
            template="plotly_white",
            title="World totals — " + "  |  ".join(bits),
            yaxis=dict(title=dict(text="new cases / day",
                                  font=dict(color=FORECAST_HISTORY)),
                       tickfont=dict(color=FORECAST_HISTORY)),
            yaxis2=dict(title=dict(text="deaths / day",
                                   font=dict(color=FORECAST_FUTURE)),
                        tickfont=dict(color=FORECAST_FUTURE),
                        overlaying="y", side="right", showgrid=False),
            margin=dict(l=60, r=70, t=60, b=40))


    cases_fig, deaths_fig = go.Figure(), go.Figure()
    if not ts_a.empty:
        cases_fig.add_trace(go.Scatter(x=ts_a["DATE"], y=ts_a["NEW_CONFIRMED"],
                                       mode="lines", name=country_a,
                                       line=dict(color=COUNTRY_A_COLOR, width=2)))
        deaths_fig.add_trace(go.Scatter(x=ts_a["DATE"], y=ts_a["NEW_DEATHS"],
                                        mode="lines", name=country_a,
                                        line=dict(color=COUNTRY_A_COLOR, width=2)))
    if country_b and not ts_b.empty:
        cases_fig.add_trace(go.Scatter(x=ts_b["DATE"], y=ts_b["NEW_CONFIRMED"],
                                       mode="lines", name=country_b,
                                       line=dict(color=COUNTRY_B_COLOR, width=2)))
        deaths_fig.add_trace(go.Scatter(x=ts_b["DATE"], y=ts_b["NEW_DEATHS"],
                                        mode="lines", name=country_b,
                                        line=dict(color=COUNTRY_B_COLOR, width=2)))
    cases_fig.update_layout(template="plotly_white", title=f"Daily new confirmed cases - {title_suffix}",
                            yaxis_title="new cases / day", margin=dict(l=50, r=20, t=50, b=40))
    deaths_fig.update_layout(template="plotly_white", title=f"Daily deaths - {title_suffix}",
                             yaxis_title="new deaths / day", margin=dict(l=50, r=20, t=50, b=40))

    ENRICHED_ALL = get_all_enriched()
    region_fig = go.Figure()
    if not ENRICHED_ALL.empty and "REGION" in ENRICHED_ALL.columns:
        region_avg = (
            ENRICHED_ALL.dropna(subset=["REGION", "DEATHS_PER_100K"])
            .groupby("REGION")["DEATHS_PER_100K"].mean().sort_values()
        )

        def region_of(country):
            rows_ = ENRICHED_ALL[ENRICHED_ALL["COUNTRY_REGION"] == country]
            return rows_.iloc[0]["REGION"] if not rows_.empty else None

        region_a = region_of(country_a)
        region_b = region_of(country_b) if country_b else None
        colors = [
            COUNTRY_A_COLOR if r == region_a else COUNTRY_B_COLOR if r == region_b else "lightgray"
            for r in region_avg.index
        ]
        region_fig.add_trace(go.Bar(x=region_avg.values, y=region_avg.index,
                                    orientation="h", marker=dict(color=colors)))
        region_fig.update_layout(template="plotly_white", xaxis_title="avg deaths / 100k",
                                 margin=dict(l=170, r=20, t=20, b=40))

    scatter_fig = go.Figure()
    if not ENRICHED_ALL.empty:
        highlight_map = {country_a: COUNTRY_A_COLOR}
        if country_b:
            highlight_map[country_b] = COUNTRY_B_COLOR
        others = ENRICHED_ALL[~ENRICHED_ALL["COUNTRY_REGION"].isin(list(highlight_map))]
        scatter_fig.add_trace(go.Scatter(
            x=others["GDP_PER_CAPITA"], y=others["DEATHS_PER_100K"],
            mode="markers", text=others["COUNTRY_REGION"], name="Other countries",
            marker=dict(color="lightgray"),
        ))
        for name, color in highlight_map.items():
            sel = ENRICHED_ALL[ENRICHED_ALL["COUNTRY_REGION"] == name]
            scatter_fig.add_trace(go.Scatter(
                x=sel["GDP_PER_CAPITA"], y=sel["DEATHS_PER_100K"],
                mode="markers+text", text=sel["COUNTRY_REGION"], textposition="top center",
                name=name, marker=dict(color=color, size=14),
            ))
        scatter_fig.update_layout(template="plotly_white", xaxis_title="GDP per capita ($)",
                                  yaxis_title="Deaths per 100,000", margin=dict(l=50, r=20, t=20, b=40))

    # --- Vaccination vs excess mortality, coloured by median age ---
    vax_fig = go.Figure()
    needed = {"VACCINATED_PCT", "EXCESS_DEATHS_PER_MILLION", "MEDIAN_AGE"}
    if not ENRICHED_ALL.empty and needed.issubset(ENRICHED_ALL.columns):
        vax = ENRICHED_ALL.dropna(subset=list(needed))
        raw_r, adj_r = partial_correlation(
            vax, "VACCINATED_PCT", "EXCESS_DEATHS_PER_MILLION", "MEDIAN_AGE")

        selected = {country_a}
        if country_b:
            selected.add(country_b)
        others = vax[~vax["COUNTRY_REGION"].isin(selected)]

        vax_fig.add_trace(go.Scatter(
            x=others["VACCINATED_PCT"], y=others["EXCESS_DEATHS_PER_MILLION"],
            mode="markers", text=others["COUNTRY_REGION"],
            name="Countries",
            hovertemplate="%{text}<br>vaccinated %{x:.1f}%"
                          "<br>excess deaths %{y:,.0f}/M"
                          "<br>median age %{marker.color:.1f}<extra></extra>",
            marker=dict(
                size=10,
                color=others["MEDIAN_AGE"],
                colorscale="RdYlBu_r",   # blue = young, red = old
                showscale=True,
                colorbar=dict(title="Median<br>age", x=1.02, len=0.9),
                line=dict(color="white", width=0.5),
            )))
        for name, color in ((country_a, COUNTRY_A_COLOR), (country_b, COUNTRY_B_COLOR)):
            if not name:
                continue
            sel = vax[vax["COUNTRY_REGION"] == name]
            if sel.empty:
                continue
            vax_fig.add_trace(go.Scatter(
                x=sel["VACCINATED_PCT"], y=sel["EXCESS_DEATHS_PER_MILLION"],
                mode="markers+text", text=[name], textposition="top center",
                name=name, hovertemplate=f"{name}<extra></extra>",
                marker=dict(color=color, size=18, symbol="star",
                            line=dict(color="black", width=1.5))))

        parts = [f"{len(vax)} countries"]
        if raw_r is not None:
            parts.append(f"raw r = {raw_r:+.2f}")
        if adj_r is not None:
            parts.append(f"age-adjusted r = {adj_r:+.2f}")
        vax_fig.update_layout(
            template="plotly_white",
            title="Vaccination vs excess mortality  (" + ",  ".join(parts) + ")",
            xaxis_title="People vaccinated (% of population)",
            yaxis_title="Cumulative excess deaths per million",
            margin=dict(l=60, r=140, t=80, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))

    # --- Forecast chart (Country A on the left axis, B on the right) ---
    forecast_fig = go.Figure()
    titles = []
    for country, palette in (
        (country_a, (FORECAST_HISTORY, FORECAST_TEST, FORECAST_FUTURE)),
        (country_b, (FORECAST_HISTORY_B, FORECAST_TEST_B, FORECAST_FUTURE_B)),
    ):
        if not country:
            continue

        # Separate y-axis per country: daily case counts can differ by
        # an order of magnitude (e.g. US vs UK), and on a shared axis
        # the smaller country flattens into an unreadable line.
        axis = "y" if country == country_a else "y2"

        fc = fetch_forecast(country)
        if not fc or not fc.get("history"):
            titles.append(f"{country}: no forecast (not enough reported data)")
            continue

        c_hist, c_test, c_future = palette
        hist = pd.DataFrame(fc["history"])
        test = pd.DataFrame(fc["test_forecast"])
        future = pd.DataFrame(fc["future_forecast"])

        forecast_fig.add_trace(go.Scatter(
            x=hist["DATE"], y=hist["VALUE"], mode="lines", yaxis=axis,
            name=f"{country} - history", line=dict(color=c_hist, width=2)))
        forecast_fig.add_trace(go.Scatter(
            x=test["DATE"], y=test["VALUE"], mode="lines", yaxis=axis,
            name=f"{country} - back-test", line=dict(color=c_test, width=2, dash="dash")))
        forecast_fig.add_trace(go.Scatter(
            x=future["DATE"], y=future["VALUE"], mode="lines", yaxis=axis,
            name=f"{country} - forecast", line=dict(color=c_future, width=3)))

        # MASE first: it is the reliable metric at this scale. MAPE is
        # kept for completeness but inflates badly once daily counts
        # drop to single digits at the end of the series.
        mase, mape = fc.get("mase"), fc.get("mape")
        bits = []
        if mase is not None:
            bits.append(f"MASE {mase:.2f}")
        if mape is not None:
            bits.append(f"MAPE {mape:.0f}%")
        bits.append(f"MAE {fc.get('mae', 0):,.0f}/day")
        titles.append(f"{country}: " + ", ".join(bits))

    forecast_fig.update_layout(
        template="plotly_white",
        title=("Case forecast — " + "   |   ".join(titles)) if titles else "Case forecast",
        yaxis=dict(
            title=dict(text=f"{country_a} - new cases / day",
                       font=dict(color=FORECAST_HISTORY)),
            tickfont=dict(color=FORECAST_HISTORY)),
        yaxis2=dict(
            title=dict(text=f"{country_b} - new cases / day" if country_b else "",
                       font=dict(color=FORECAST_HISTORY_B)),
            tickfont=dict(color=FORECAST_HISTORY_B),
            overlaying="y", side="right", showgrid=False),
        margin=dict(l=60, r=70, t=60, b=40))

    # --- Cluster chart (PCA-projected, A/B starred) ---
    cluster_fig = go.Figure()
    clusters_df = fetch_clusters()
    if not clusters_df.empty and "PCA_X" in clusters_df.columns:
        selected = {country_a}
        if country_b:
            selected.add(country_b)
        for cid in sorted(clusters_df["CLUSTER"].unique()):
            grp = clusters_df[(clusters_df["CLUSTER"] == cid)
                              & (~clusters_df["COUNTRY_REGION"].isin(selected))]
            cluster_fig.add_trace(go.Scatter(
                x=grp["PCA_X"], y=grp["PCA_Y"], mode="markers",
                name=f"Cluster {cid}", text=grp["COUNTRY_REGION"],
                hovertemplate="%{text}<extra></extra>",
                marker=dict(color=CLUSTER_PALETTE[cid % len(CLUSTER_PALETTE)],
                            size=9, opacity=0.75)))
        for name in selected:
            row = clusters_df[clusters_df["COUNTRY_REGION"] == name]
            if not row.empty:
                cid = int(row.iloc[0]["CLUSTER"])
                cluster_fig.add_trace(go.Scatter(
                    x=row["PCA_X"], y=row["PCA_Y"],
                    mode="markers+text", text=[name], textposition="top center",
                    name=f"{name} (cluster {cid})",
                    hovertemplate=f"{name}<extra></extra>",
                    marker=dict(color=CLUSTER_PALETTE[cid % len(CLUSTER_PALETTE)],
                                size=22, symbol="star",
                                line=dict(color="black", width=1.5))))
        cluster_fig.update_layout(
            template="plotly_white",
            xaxis_title="Principal component 1", yaxis_title="Principal component 2",
            margin=dict(l=50, r=20, t=20, b=40))

    return (cards, global_fig, cases_fig, deaths_fig, region_fig, scatter_fig,
            vax_fig, forecast_fig, cluster_fig)


@app.callback(
    Output("annotations-list", "children"),
    Output("new-comment", "value"),
    Output("annotation-form-status", "children"),
    Input("country-a-dropdown", "value"),
    Input("country-b-dropdown", "value"),
    Input("submit-annotation", "n_clicks"),
    State("new-author", "value"),
    State("new-email", "value"),
    State("new-comment", "value"),
    State("annotation-target-dropdown", "value"),
)
def manage_annotations(country_a, country_b, n_clicks, author, email, comment, target_country):
    country_b = country_b or None
    status = ""
    cleared_comment = dash.no_update

    if ctx.triggered_id == "submit-annotation":
        if not comment or not comment.strip():
            status = status_msg("Please write a comment before submitting.", True)
        elif not email or not EMAIL_RE.match(email.strip()):
            status = status_msg("Please enter a valid email address to submit a comment.", True)
        else:
            payload = {
                "country": target_country or country_a,
                "date": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "metric": "general",
                "comment": comment,
                "author": author or "Anonymous",
                "email": email.strip(),
                "tags": [],
                "source_url": None,
            }
            resp = requests.post(f"{API_URL}/annotations", json=payload, timeout=10)
            if resp.ok:
                cleared_comment = ""
                status = status_msg("Comment posted.", False)
            else:
                status = status_msg(
                    "Could not save the comment - please check the email format and try again.",
                    True,
                )

    def panel(country):
        if not country:
            return None
        resp = requests.get(f"{API_URL}/annotations/{country}", timeout=10)
        docs = resp.json() if resp.ok else []
        if not docs:
            items = [html.P("No annotations yet.",
                            style={"color": MUTED, "fontStyle": "italic", "fontSize": "13px"})]
        else:
            items = [
                html.Div([
                    html.Div([
                        html.Span(d["author"], style={"fontWeight": "700", "color": INK}),
                        html.Span(f"  ·  {d['date']}", style={"color": MUTED, "fontSize": "12px"}),
                    ]),
                    html.Div(d["comment"], style={"marginTop": "4px", "color": INK}),
                ], style=ANNOTATION_STYLE)
                for d in docs
            ]
        return html.Div([
            html.H4(country, style={"margin": "0 0 8px 0", "color": INK, "fontSize": "15px"}),
            html.Div(items),
        ], style={"flex": "1", "minWidth": "260px"})

    panels = [p for p in (panel(country_a), panel(country_b)) if p is not None]
    layout = html.Div(panels, style={"display": "flex", "gap": "24px", "flexWrap": "wrap"})

    return layout, cleared_comment, status


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)