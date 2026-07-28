# Task 3: NoSQL schema setup.
# Creates the `annotations` collection, which stores supplementary
# free-text data that doesn't belong in Snowflake: comments on
# specific data points, context notes, and links to outside sources.
# Task 4's API and Task 5's dashboard both read/write this collection.

from datetime import datetime, timezone

from mongo_connect import get_annotations_collection

SAMPLE_ANNOTATIONS = [
    {
        "country": "Peru",
        "date": "2021-08-15",
        "metric": "deaths",
        "comment": (
            "Peru revised its official death count sharply upward in "
            "mid-2021 after changing its case-definition methodology, "
            "which is why its per-capita death rate looks unusually "
            "high compared to neighboring countries."
        ),
        "author": "Sennur Bascetin",
        "tags": ["methodology-change", "case-definition"],
        "source_url": "https://ourworldindata.org/covid-excess-mortality",
        "created_at": datetime.now(timezone.utc),
    },
    {
        "country": "Bulgaria",
        "date": "2021-11-01",
        "metric": "cases",
        "comment": (
            "Low vaccination uptake during the Delta wave is often "
            "cited as a factor in Bulgaria's high mortality rate."
        ),
        "author": "Sennur Bascetin",
        "tags": ["vaccination", "delta-wave"],
        "source_url": None,
        "created_at": datetime.now(timezone.utc),
    },
]


def main():
    collection = get_annotations_collection()

    # Compound index on (country, date): matches the lookup the API
    # will do most often - "give me annotations for country X" -
    # so Mongo can use the index instead of scanning every document.
    collection.create_index([("country", 1), ("date", 1)])

    result = collection.insert_many(SAMPLE_ANNOTATIONS)
    print(f"Inserted {len(result.inserted_ids)} sample annotations.")

    print("\nAll annotations currently in the collection:")
    for doc in collection.find():
        print(f"- {doc['country']} ({doc['date']}): {doc['comment'][:60]}...")


if __name__ == "__main__":
    main()