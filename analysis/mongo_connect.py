# Shared MongoDB connection helper (mirrors sf_connect.py's pattern:
# credentials and connection logic live here once, every script
# that needs Mongo imports from this file).

import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def get_mongo_client():
    password = os.getenv("MONGO_PASSWORD")
    uri = f"mongodb://covid_admin:{password}@localhost:27017/?authSource=admin"
    return MongoClient(uri)


def get_annotations_collection():
    client = get_mongo_client()
    db = client["covid_platform"]
    return db["annotations"]