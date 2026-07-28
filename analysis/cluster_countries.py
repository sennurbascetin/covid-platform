# Task 6 (Bonus): Clustering.
# Groups countries by similarity in COVID-19 outcomes (cases/deaths
# per 100k) together with the demographic context that helps explain
# WHY outcomes differ (GDP per capita, literacy rate) - all pulled
# straight from the COUNTRY_ENRICHED table built in Task 2b.

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from sf_connect import get_connection, fetch_df

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

FEATURES = ["GDP_PER_CAPITA", "LITERACY_PCT", "CASES_PER_100K", "DEATHS_PER_100K"]
N_CLUSTERS = 4


def main():
    conn = get_connection()
    try:
        df = fetch_df(conn, "SELECT * FROM COVID_PROJECT.ANALYTICS.COUNTRY_ENRICHED")
    finally:
        conn.close()

    before = len(df)
    df = df.dropna(subset=FEATURES).reset_index(drop=True)
    print(f"Using {len(df)} / {before} countries (dropped rows with missing values).")

    X = StandardScaler().fit_transform(df[FEATURES])

    # Elbow curve: shows how much inertia (within-cluster spread)
    # drops as k grows, to justify N_CLUSTERS=4 rather than picking
    # it arbitrarily.
    inertias = [
        KMeans(n_clusters=k, n_init=10, random_state=42).fit(X).inertia_
        for k in range(2, 9)
    ]
    plt.figure(figsize=(7, 4))
    plt.plot(range(2, 9), inertias, marker="o")
    plt.axvline(N_CLUSTERS, color="firebrick", linestyle="--", label=f"chosen k={N_CLUSTERS}")
    plt.xlabel("number of clusters (k)")
    plt.ylabel("inertia")
    plt.title("Elbow curve for choosing k")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "cluster_elbow.png", dpi=150)
    plt.close()

    kmeans = KMeans(n_clusters=N_CLUSTERS, n_init=10, random_state=42).fit(X)
    df["CLUSTER"] = kmeans.labels_

    # PCA projects the 4 standardized features down to 2 dimensions
    # for plotting, keeping as much of their variation as possible -
    # cleaner than arbitrarily picking two of the four features.
    coords = PCA(n_components=2, random_state=42).fit_transform(X)
    df["PCA_X"], df["PCA_Y"] = coords[:, 0], coords[:, 1]

    plt.figure(figsize=(9, 6))
    for cid in sorted(df["CLUSTER"].unique()):
        subset = df[df["CLUSTER"] == cid]
        plt.scatter(subset["PCA_X"], subset["PCA_Y"], label=f"Cluster {cid}", alpha=0.7)
    plt.xlabel("Principal component 1")
    plt.ylabel("Principal component 2")
    plt.title("Countries clustered by COVID outcomes + demographic context")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "cluster_scatter.png", dpi=150)
    plt.close()

    summary = df.groupby("CLUSTER")[FEATURES].mean().round(1)
    counts = df["CLUSTER"].value_counts().sort_index()

    lines = [
        "# Clustering Report (Task 6 Bonus)",
        f"\nClustered {len(df)} countries into {N_CLUSTERS} groups using K-Means",
        f"on standardized features: {', '.join(FEATURES)}.",
        "\n## Cluster sizes\n", counts.to_string(),
        "\n## Cluster averages (un-standardized, for interpretation)\n", summary.to_string(),
        "\n## Countries per cluster\n",
    ]
    for cid in sorted(df["CLUSTER"].unique()):
        names = df.loc[df["CLUSTER"] == cid, "COUNTRY_REGION"].tolist()
        lines.append(f"\n**Cluster {cid}** ({len(names)} countries): {', '.join(names)}")

    (OUTPUT_DIR / "cluster_report.md").write_text("\n".join(lines))
    print(f"\nSaved cluster_elbow.png, cluster_scatter.png, cluster_report.md to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()