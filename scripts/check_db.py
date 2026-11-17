"""Check your shadeDB setup end to end:  python scripts/check_db.py

It writes, updates and deletes a throwaway record in your partition, and tells you
whether the `room` field is a unique key (it should be).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from store import ShadeError, ShadeStore, make_store  # noqa: E402

store = make_store(ROOT)
print("Backend:", store.name)
if not isinstance(store, ShadeStore):
    sys.exit("No shadeDB credentials in .env (or HD_MODE=offline). Nothing to check.")

KEY = "hd_selfcheck"


def rows():
    out = store.client.query(f"{store._head()}FETCH;\nstr<room>::str<{KEY}>;")
    return [r for r in (out if isinstance(out, list) else [out]) if isinstance(r, dict) and r.get("room") == KEY]


def cleanup():
    for _ in range(4):
        try:
            store.delete(KEY)
        except ShadeError:
            break


try:
    cleanup()
    store.put(KEY, {"rev": 1, "updated": 1}, new=True)
    print("INSERT    ok")
    unique = False
    try:
        store.put(KEY, {"rev": 1, "updated": 1}, new=True)
    except ShadeError as exc:
        unique = exc.code == "ERR_STORAGE_CONSTRAINT_VIOLATION"
    print("UNIQUE   ", "yes, `room` is a unique key" if unique else "NO: a second INSERT of the same room was accepted")
    store.put(KEY, {"rev": 2, "updated": 2})
    found = rows()
    print("UPDATE    ok, records for this room:", len(found), "| revs:", [__import__("json").loads(r["data"])["rev"] for r in found])
    cleanup()
    print("DELETE    ok")
    if unique and len(found) == 1:
        print("\nAll good. shadeDB is ready for Heaven Duels.")
    elif isinstance(unique, str):
        print("\nProblem: `room` is not a unique key in partition '%s'." % store.partition)
        print("Open the partition in the shadeDB dashboard, mark `room` as a unique field, and run this again.")
        print("Until then the game still works (it picks the newest copy), but duplicate records can pile up.")
except Exception as exc:
    cleanup()
    sys.exit(f"Check failed: {exc}\nSee README, Troubleshooting.")
