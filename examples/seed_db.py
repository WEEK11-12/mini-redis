"""Create the SQLite file read by the example origin API."""

import argparse
import json
import os
import sqlite3
import tempfile

DEMO_ID = "demo"
DEMO_VALUE = "sample-response"
ROWS = 10000
# Every row stores a value of the same size as the demo value.
VALUE_BYTES = len(DEMO_VALUE.encode("utf-8"))


def seed(path, rows=ROWS):
    """Replace path with a table of `rows` rows keyed by TEXT primary key."""
    if rows < 1:
        raise ValueError("rows must be at least 1")
    # A unique sibling file plus os.replace lets concurrent seeders swap in whole files only.
    handle, temporary = tempfile.mkstemp(suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
    os.close(handle)
    try:
        connection = sqlite3.connect(temporary)
        try:
            with connection:
                connection.execute("CREATE TABLE items (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("INSERT INTO items VALUES (?, ?)", (DEMO_ID, DEMO_VALUE))
                connection.executemany("INSERT INTO items VALUES (?, ?)",
                                       ((f"item-{i}", f"value-{i:09d}") for i in range(1, rows)))
        finally:
            connection.close()
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return {"path": os.path.abspath(path), "rows": rows, "value_bytes": VALUE_BYTES,
            "file_bytes": os.path.getsize(path)}


def main():
    parser = argparse.ArgumentParser(description="Create the example origin SQLite database")
    parser.add_argument("--db", required=True)
    parser.add_argument("--rows", type=int, default=ROWS)
    args = parser.parse_args()
    print(json.dumps(seed(args.db, args.rows)))


if __name__ == "__main__":
    main()
