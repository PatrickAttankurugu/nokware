import json
import time

import httpx

from nokware.core import Check, CheckResult, Suite
from nokware.judge import Judge
from nokware.scorers import p95

ASK_PATH = "/api/query"  # POST {"question": str, "jurisdiction": str} -> corrected in Task 11 Step 1
RATE_LIMIT_SLEEP_S = 2.5  # LexAura allows 30 req/min; pace golden queries to stay under that


def build_suite(base_url: str, judge: Judge,
                golden_path: str = "golden/lexaura.jsonl") -> Suite:
    entries = [json.loads(l) for l in open(golden_path, encoding="utf8") if l.strip()]
    state: dict = {}

    def gather() -> CheckResult:
        client = httpx.Client()
        answers, latencies, errors = {}, [], 0
        errored_ids = []
        for i, e in enumerate(entries):
            if i > 0:
                time.sleep(RATE_LIMIT_SLEEP_S)
            t0 = time.monotonic()
            try:
                resp = client.post(
                    base_url.rstrip("/") + ASK_PATH,
                    json={"question": e["question"], "jurisdiction": e.get("jurisdiction", "all"), "include_full_context": True},
                    timeout=60,
                )
                resp.raise_for_status()
                answers[e["id"]] = (resp.json(), e)
                latencies.append((time.monotonic() - t0) * 1000)
            except Exception as exc:
                errors += 1
                state.setdefault("errors", []).append({"id": e["id"], "error": str(exc)})
                errored_ids.append(e["id"])
                # forced miss, not a dropped denominator: an errored query still counts
                # against retrieval_hit_rate, citation_integrity, and faithfulness below
                answers[e["id"]] = ({"answer": "", "sources": []}, e)
        state.update(answers=answers, latencies=latencies, errored_ids=errored_ids)
        availability = 1.0 - (errors / len(entries) if entries else 0.0)
        return CheckResult(check_id="availability", suite="lexaura",
                           score_type="deterministic", value=round(availability, 4),
                           passed=availability >= 0.95, traces={"errors": state.get("errors", [])})

    def _context(payload: dict) -> str:
        # LexAura's sources[].body is the regulatory body name (e.g. "Central Bank of Nigeria"),
        # not chunk text. When include_full_context is true, sources[].full_text carries the
        # complete retrieved chunk; otherwise sources[].snippet (truncated to 150 chars) is used.
        # retrieval_hit_rate and faithfulness check against the most complete context available.
        return " ".join(s.get("full_text") or s.get("snippet", "") for s in payload.get("sources", []))

    def _citations(payload: dict) -> list[str]:
        return [s.get("title", "") for s in payload.get("sources", [])]

    def retrieval_hit_rate() -> CheckResult:
        hits, misses = 0, []
        errored_ids = state.get("errored_ids", [])
        has_full_text = False
        for qid, (payload, e) in state["answers"].items():
            context = _context(payload).lower()
            sources = payload.get("sources", [])
            if any(s.get("full_text") for s in sources):
                has_full_text = True
            if e["source_quote"].lower() in context:
                hits += 1
            else:
                misses.append({"id": qid, "expected_quote": e["source_quote"][:80]})
        n = len(state["answers"]) or 1
        score = hits / n
        context_mode = "full_text" if has_full_text else "snippet"
        return CheckResult(check_id="retrieval_hit_rate", suite="lexaura",
                           score_type="statistical", value=round(score, 4),
                           passed=score >= 0.8, traces={"misses": misses, "errored": errored_ids, "context_mode": context_mode})

    def citation_integrity() -> CheckResult:
        ok, bad = 0, []
        errored_ids = state.get("errored_ids", [])
        for qid, (payload, e) in state["answers"].items():
            cites = _citations(payload)
            if any(e["must_cite"].lower() in c.lower() for c in cites):
                ok += 1
            else:
                bad.append({"id": qid, "expected": e["must_cite"], "got": cites})
        n = len(state["answers"]) or 1
        score = ok / n
        return CheckResult(check_id="citation_integrity", suite="lexaura",
                           score_type="deterministic", value=round(score, 4),
                           passed=score >= 0.8, traces={"bad": bad, "errored": errored_ids})

    def faithfulness() -> CheckResult:
        scores, unsupported = [], []
        errored_ids = set(state.get("errored_ids", []))
        engines = {"gemini": 0, "fallback": 0}
        for qid, (payload, e) in state["answers"].items():
            if qid in errored_ids:
                # already known to be a forced miss (the POST raised); don't spend
                # judge budget confirming it, and don't let it pollute the engine tally
                scores.append(0.0)
                unsupported.append({"id": qid, "reasons": ["query errored"], "engine": None})
                continue
            verdict = judge.judge_faithfulness(payload.get("answer", ""), _context(payload))
            scores.append(verdict.score)
            engines[verdict.engine] = engines.get(verdict.engine, 0) + 1
            if not verdict.supported:
                unsupported.append({"id": qid, "reasons": verdict.reasons, "engine": verdict.engine})
        score = sum(scores) / len(scores) if scores else 0.0
        return CheckResult(check_id="faithfulness", suite="lexaura",
                           score_type="llm_judge", value=round(score, 4),
                           passed=score >= 0.85, traces={"unsupported": unsupported,
                                                          "errored": sorted(errored_ids),
                                                          "engines": engines})

    def latency() -> CheckResult:
        v = p95(state["latencies"])
        passed = (v < 15000) and not state.get("errors") and bool(state["latencies"])
        return CheckResult(check_id="p95_latency_ms", suite="lexaura",
                           score_type="deterministic", value=round(v, 1),
                           passed=passed, traces={"n": len(state["latencies"]),
                                                  "errored_queries": len(state.get("errors", []))})

    return Suite(name="lexaura", checks=[
        Check(id="availability", suite="lexaura", description="gather", fn=gather),
        Check(id="retrieval_hit_rate", suite="lexaura", description="known passage retrieved", fn=retrieval_hit_rate),
        Check(id="citation_integrity", suite="lexaura", description="citations exist", fn=citation_integrity),
        Check(id="faithfulness", suite="lexaura", description="claims supported by context", fn=faithfulness),
        Check(id="p95_latency_ms", suite="lexaura", description="p95 latency", fn=latency),
    ])
