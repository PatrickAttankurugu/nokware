"""Verify golden entries resolve against the live API. Usage:
   python scripts/verify_golden.py golden/africapep.jsonl
"""
import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from suites.africapep import search_names

base = os.environ["AFRICAPEP_BASE_URL"].rstrip("/")
key = os.environ["AFRICAPEP_API_KEY"]
failures = 0
client = httpx.Client()
for i, line in enumerate(open(sys.argv[1], encoding="utf8")):
    if not line.strip():
        continue
    if i > 0:
        time.sleep(0.3)  # pace requests politely against the live API
    e = json.loads(line)
    results = search_names(client, base, key, e["query"], e.get("country"))
    if e["kind"] == "positive":
        window = results[: e["max_rank"]]
        if e.get("expect_qid"):
            hit = any(r.get("id") == e["expect_qid"] for r in window)
        else:
            hit = any(e["expect_name"].lower() in r["full_name"].lower() for r in window)
        status = "OK" if hit else "MISS"
    else:
        status = "OK" if not results else f"UNEXPECTED {[r['full_name'] for r in results[:2]]}"
    if not status.startswith("OK"):
        failures += 1
    print(f"{status:>10}  {e['id']}")
sys.exit(1 if failures else 0)
