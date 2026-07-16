import json
import time

import httpx

from nokware.core import Check, CheckResult, Suite
from nokware.scorers import mrr, p95, precision_at_k, recall_at_k

SEARCH_PATH = "/api/v1/search"  # GET, params: q (required), country (optional ISO2)
AUTH_HEADER = "X-API-Key"       # middleware exists but is currently disabled in prod


def search_names(client: httpx.Client, base: str, key: str,
                 query: str, country: str | None) -> list[dict]:
    """Returns ranked result items with both `id` (stable Wikidata QID, e.g.
    "wd:Q50678") and `full_name`. Identity (`id`) is the authoritative match
    key; `full_name` is kept for readability in traces and for golden
    entries that predate the QID scheme."""
    params = {"q": query}
    if country:
        params["country"] = country
    resp = client.get(base.rstrip("/") + SEARCH_PATH, params=params,
                      headers={AUTH_HEADER: key}, timeout=15)
    resp.raise_for_status()
    return [{"id": item.get("id"), "full_name": item["full_name"]}
            for item in resp.json().get("results", [])]


def build_suite(base_url: str, api_key: str,
                golden_path: str = "golden/africapep.jsonl") -> Suite:
    entries = [json.loads(l) for l in open(golden_path, encoding="utf8") if l.strip()]
    positives = [e for e in entries if e["kind"] == "positive"]
    negatives = [e for e in entries if e["kind"] == "negative"]

    state: dict = {}

    def gather() -> CheckResult:
        """Runs all queries once; downstream checks read from state."""
        client = httpx.Client()
        latencies, errors = [], 0
        pos_ranked, neg_hits = {}, {}
        for e in positives + negatives:
            t0 = time.monotonic()
            try:
                results = search_names(client, base_url, api_key, e["query"], e.get("country"))
                latencies.append((time.monotonic() - t0) * 1000)
            except Exception as exc:
                errors += 1
                state.setdefault("errors", []).append({"id": e["id"], "error": str(exc)})
                state.setdefault("errored_ids", set()).add(e["id"])
                results = []
            if e["kind"] == "positive":
                pos_ranked[e["id"]] = (results, e)
            else:
                neg_hits[e["id"]] = results
        state.update(pos_ranked=pos_ranked, neg_hits=neg_hits, latencies=latencies)
        total = len(positives) + len(negatives)
        availability = 1.0 - (errors / total if total else 0.0)
        return CheckResult(check_id="availability", suite="africapep",
                           score_type="deterministic", value=round(availability, 4),
                           passed=availability >= 0.99,
                           traces={"errors": state.get("errors", [])})

    def relevant_and_ranked(item):
        """A result is relevant iff its `id` matches the golden entry's
        `expect_qid` (identity-based match on the stable Wikidata QID).
        Falls back to name-substring matching only for entries that predate
        the QID scheme and carry no `expect_qid`."""
        results, e = item
        ranked = [r["id"] if e.get("expect_qid") else r["full_name"] for r in results]
        if e.get("expect_qid"):
            rel = {e["expect_qid"]} & set(ranked)
        else:
            rel = {n for n in ranked if e["expect_name"].lower() in n.lower()}
        return ranked, rel, e, results

    def stat_check(check_id, fn, threshold) -> Check:
        def run() -> CheckResult:
            vals, misses = [], []
            for item in state["pos_ranked"].values():
                ranked, rel, e, results = relevant_and_ranked(item)
                v = fn(ranked, rel)
                vals.append(v)
                if v == 0.0:
                    top = [f"{r.get('id')} {r['full_name']}" for r in results[:5]]
                    misses.append({"id": e["id"], "query": e["query"], "top": top})
            score = sum(vals) / len(vals) if vals else 0.0
            return CheckResult(check_id=check_id, suite="africapep",
                               score_type="statistical", value=round(score, 4),
                               passed=score >= threshold, traces={"misses": misses})
        return Check(id=check_id, suite="africapep", description=check_id, fn=run)

    def negative_controls() -> CheckResult:
        errored_ids = state.get("errored_ids", set())
        errored = [e["id"] for e in negatives if e["id"] in errored_ids]
        bad = {k: [r["full_name"] for r in v[:3]] for k, v in state["neg_hits"].items() if v}
        clean = len(negatives) - len(bad) - len(errored)
        score = clean / len(negatives) if negatives else 0.0
        passed = not bad and not errored
        return CheckResult(check_id="negative_controls", suite="africapep",
                           score_type="deterministic", value=round(score, 4),
                           passed=passed, traces={"false_positives": bad, "errored": errored})

    def latency() -> CheckResult:
        v = p95(state["latencies"])
        passed = (v < 2000) and not state.get("errors") and bool(state["latencies"])
        return CheckResult(check_id="p95_latency_ms", suite="africapep",
                           score_type="deterministic", value=round(v, 1),
                           passed=passed, traces={"n": len(state["latencies"]),
                                                  "errored_queries": len(state.get("errors", []))})

    return Suite(name="africapep", checks=[
        Check(id="availability", suite="africapep", description="gather + availability", fn=gather),
        stat_check("precision_at_5", lambda n, r: precision_at_k(n, r, 5), 0.85),
        stat_check("recall_at_10", lambda n, r: recall_at_k(n, r, 10), 0.85),
        stat_check("mrr", mrr, 0.80),
        Check(id="negative_controls", suite="africapep", description="no false PEP hits", fn=negative_controls),
        Check(id="p95_latency_ms", suite="africapep", description="p95 latency", fn=latency),
    ])
