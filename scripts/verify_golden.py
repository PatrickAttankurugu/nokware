"""Verify golden entries resolve against the live API. Usage:
   python scripts/verify_golden.py golden/africapep.jsonl
"""
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from suites.africapep import search_names

base = os.environ["AFRICAPEP_BASE_URL"].rstrip("/")
key = os.environ["AFRICAPEP_API_KEY"]
failures = 0
for line in open(sys.argv[1], encoding="utf8"):
    e = json.loads(line)
    names = search_names(httpx.Client(), base, key, e["query"], e.get("country"))
    if e["kind"] == "positive":
        hit = any(e["expect_name"].lower() in n.lower() for n in names[: e["max_rank"]])
        status = "OK" if hit else "MISS"
    else:
        status = "OK" if not names else f"UNEXPECTED {names[:2]}"
    if not status.startswith("OK"):
        failures += 1
    print(f"{status:>10}  {e['id']}")
sys.exit(1 if failures else 0)
