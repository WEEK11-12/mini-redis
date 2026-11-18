"""Seed the MongoDB collection read by the example origin API (needs pymongo)."""

import argparse
import json
import random

from examples.origin_api import DEMO_ID, DEMO_VALUE

DATABASE = "mini_redis_origin"
COLLECTION = "items"
DOCS = 1_000_000
VALUE_BYTES = 1024
BATCH = 10_000


def item_id(number):
    return f"item-{number}"


def value_for(number):
    """Deterministic, hard-to-compress value so readers can verify without the database."""
    return random.Random(number).randbytes(VALUE_BYTES // 2).hex()


def collection(uri):
    from pymongo import MongoClient  # optional dependency, only for the MongoDB backend

    client = MongoClient(uri, serverSelectionTimeoutMS=3000, socketTimeoutMS=3000)
    return client, client[DATABASE][COLLECTION]


def seed(uri, docs=DOCS):
    """Replace the collection with `docs` items plus the demo document."""
    if docs < 1:
        raise ValueError("docs must be at least 1")
    client, items = collection(uri)
    try:
        items.drop()
        items.insert_one({"_id": DEMO_ID, "value": DEMO_VALUE})
        for start in range(0, docs, BATCH):
            items.insert_many([{"_id": item_id(n), "value": value_for(n)}
                               for n in range(start, min(start + BATCH, docs))], ordered=False)
        stats = client[DATABASE].command("collStats", COLLECTION)
        return {"docs": docs, "value_bytes": VALUE_BYTES, "count": stats["count"],
                "data_bytes": stats["size"], "storage_bytes": stats["storageSize"],
                "index_bytes": stats["totalIndexSize"]}
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="Seed the example origin MongoDB collection")
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--docs", type=int, default=DOCS)
    args = parser.parse_args()
    print(json.dumps(seed(args.mongo_uri, args.docs)))


if __name__ == "__main__":
    main()
