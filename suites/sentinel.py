import json
import time

import httpx

from nokware.core import Check, CheckResult, Suite
from nokware.scorers import p95

# --- Discovered API shape (Task 12 live discovery, 2026-07-16) ---
# GET  /api/v1/alerts/?limit=100          -> {"alerts": [...], "total": N}
#      alert.raw_data.scenario is ground truth (e.g. "structuring")
# GET  /api/v1/investigations/?limit=100  -> {"investigations": [...], "total": N}
#      investigation.alert_id links back to the alert
# POST /api/v1/investigations/{id}/run    -> {"status": "running", ...}
#      sets investigation.status = "in_progress" immediately and runs the
#      5-agent LangGraph workflow via BackgroundTasks. Re-running a completed
#      investigation is allowed (no guard). Must poll the detail endpoint.
# GET  /api/v1/investigations/{id}        -> adds "findings": [...] and
#      "findings_summary": {..., "typologies_detected": [str, ...], ...}
# GET  /api/v1/sar/?limit=100             -> read-only list of SAR drafts
#      (SARResponse: narrative, risk_indicators, status always populated;
#      reference_number is only set by the separate /sar/generate agent path
#      and is null on the SAR auto-created by a completed investigation, so
#      it is NOT used as a required field here)
#
# Live discovery run (structuring scenario, investigation
# 46a57095-bd19-4d9b-9a93-261f37caca44): POST /run -> polled GET detail every
# 10s -> status flipped in_progress -> completed at t=50s. findings_summary
# .typologies_detected == ["structuring", "layering"]; findings held exactly
# 5 rows, one per EXPECTED_AGENT_TYPES below; the "research" and "regulatory"
# findings carried evidence.error == "llm_unavailable" (free Gemini tier
# fallback) while the others completed cleanly with no "error" key -- that
# per-finding error field is the only self-reported signal of degraded/
# fallback execution, so it drives pipeline_completion_rate.
ALERTS_PATH = "/api/v1/alerts/"
INVESTIGATIONS_LIST_PATH = "/api/v1/investigations/"
INVESTIGATION_DETAIL_PATH = "/api/v1/investigations/{id}"
RUN_PATH = "/api/v1/investigations/{id}/run"
SAR_LIST_PATH = "/api/v1/sar/"

TERMINAL_STATUSES = {"completed", "escalated", "closed"}
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 240
MAX_POLLS = POLL_TIMEOUT_S // POLL_INTERVAL_S

# The 5 agent types that always write a Finding row when the workflow runs
# (backend/services/investigation_runner.py::_save_findings). "sar_generation"
# is a member of the Finding.AgentType enum but never appears as a Finding
# row -- its output goes to the SARReport table instead -- so it is excluded
# from the pipeline-completion denominator.
EXPECTED_AGENT_TYPES = {"research", "document_analysis", "regulatory",
                        "network_analysis", "risk_assessment"}

# network_analysis's typologies_detected uses "velocity_anomaly" for what the
# seeder (backend/seed.py) calls the "unusual_volume" scenario; alias it.
# "pep_screening" and "sanctions_match" are never emitted as network
# typologies at all -- they surface only via the research agent's
# local_watchlist_check.pep_hits / .sanctions_hits (backend/agents/research.py,
# backend/agents/risk_assessment.py), so they are matched from there instead.
TYPOLOGY_ALIASES = {"unusual_volume": {"unusual_volume", "velocity_anomaly"}}

SAR_REQUIRED_FIELDS = {"narrative", "risk_indicators", "status"}


def _latest_findings_by_agent(detail: dict) -> dict:
    """SENTINEL never dedupes Finding rows: POST /run on an already-run investigation
    (which this suite does every night) appends a fresh Finding per agent rather than
    replacing the old one, so a long-lived seeded investigation accumulates multiple
    rows per agent_type over time. The list is server-ordered by created_at ascending
    (backend/api/investigations.py), so keep only the last (most recent) row per
    agent_type -- otherwise clean-finding counts and typology detection would double
    count history and could exceed the 1.0 ceiling after enough nightly reruns."""
    latest: dict = {}
    for f in detail.get("findings", []):
        agent = f.get("agent_type")
        if agent:
            latest[agent] = f
    return latest


def _detected_typologies(detail: dict) -> set[str]:
    fs = detail.get("findings_summary") or {}
    detected = {str(t).lower() for t in fs.get("typologies_detected", []) if t}
    research = _latest_findings_by_agent(detail).get("research")
    if research:
        watchlist = (research.get("evidence") or {}).get("local_watchlist_check") or {}
        if watchlist.get("pep_hits"):
            detected.add("pep_screening")
        if watchlist.get("sanctions_hits"):
            detected.add("sanctions_match")
    return detected


def _typology_hit(expected: str, detected: set[str]) -> bool:
    aliases = TYPOLOGY_ALIASES.get(expected, {expected})
    return bool(aliases & detected)


def _clean_finding_count(detail: dict) -> int:
    """Count of expected agents (out of EXPECTED_AGENT_TYPES) whose most recent
    Finding carries no evidence.error -- an errored/fallback agent still writes a
    Finding row (see discovery note above), so absence of a Finding row is not the
    fallback signal; the per-finding evidence.error field is."""
    latest = _latest_findings_by_agent(detail)
    return sum(
        1 for agent in EXPECTED_AGENT_TYPES
        if agent in latest and not (latest[agent].get("evidence") or {}).get("error")
    )


def _sar_missing_fields(sar: dict | None) -> list[str]:
    if not sar:
        return sorted(SAR_REQUIRED_FIELDS)
    missing = []
    if not isinstance(sar.get("narrative"), str) or not sar.get("narrative"):
        missing.append("narrative")
    if not isinstance(sar.get("status"), str) or not sar.get("status"):
        missing.append("status")
    if not isinstance(sar.get("risk_indicators"), list):
        missing.append("risk_indicators")
    return missing


def build_suite(base_url: str, golden_path: str = "golden/sentinel.jsonl") -> Suite:
    entries = [json.loads(line) for line in open(golden_path, encoding="utf8") if line.strip()]
    state: dict = {}

    def _run_and_poll(client: httpx.Client, base: str, investigation_id: str) -> dict:
        resp = client.post(base + RUN_PATH.format(id=investigation_id), timeout=30)
        resp.raise_for_status()
        detail: dict = {}
        for _ in range(MAX_POLLS):
            time.sleep(POLL_INTERVAL_S)
            det_resp = client.get(base + INVESTIGATION_DETAIL_PATH.format(id=investigation_id), timeout=30)
            det_resp.raise_for_status()
            detail = det_resp.json()
            if detail.get("status") in TERMINAL_STATUSES:
                return detail
        raise TimeoutError(
            f"investigation {investigation_id} still '{detail.get('status')}' "
            f"after {POLL_TIMEOUT_S}s"
        )

    def gather() -> CheckResult:
        client = httpx.Client()
        base = base_url.rstrip("/")
        outcomes: dict = {}
        latencies: list[float] = []
        errored_ids: list[str] = []
        state["errors"] = []

        try:
            alerts = client.get(base + ALERTS_PATH, params={"limit": 100}, timeout=30)
            alerts.raise_for_status()
            scenario_to_alert = {
                a.get("raw_data", {}).get("scenario"): a["id"]
                for a in alerts.json().get("alerts", [])
            }
            invs = client.get(base + INVESTIGATIONS_LIST_PATH, params={"limit": 100}, timeout=30)
            invs.raise_for_status()
            alert_to_investigation = {
                i["alert_id"]: i["id"] for i in invs.json().get("investigations", [])
            }
        except Exception as exc:
            for e in entries:
                state["errors"].append({"id": e["id"], "error": str(exc)})
                errored_ids.append(e["id"])
                outcomes[e["id"]] = (None, e)
            state.update(outcomes=outcomes, latencies=[], errored_ids=errored_ids, sar_by_investigation={})
            return CheckResult(check_id="availability", suite="sentinel",
                               score_type="deterministic", value=0.0, passed=False,
                               traces={"errors": state["errors"]})

        for e in entries:
            t0 = time.monotonic()
            try:
                alert_id = scenario_to_alert.get(e["scenario"])
                if alert_id is None:
                    raise ValueError(f"no live alert for scenario {e['scenario']!r}")
                investigation_id = alert_to_investigation.get(alert_id)
                if investigation_id is None:
                    raise ValueError(f"no investigation linked to alert {alert_id}")
                detail = _run_and_poll(client, base, investigation_id)
                detail["_investigation_id"] = investigation_id
                latencies.append((time.monotonic() - t0) * 1000)
                outcomes[e["id"]] = (detail, e)
            except Exception as exc:
                state["errors"].append({"id": e["id"], "error": str(exc)})
                errored_ids.append(e["id"])
                outcomes[e["id"]] = (None, e)

        # Fetch SAR drafts only after every scenario has been triggered and polled to a
        # terminal state: a completed-during-this-run investigation writes its SAR row
        # synchronously inside the same background task, so reading the SAR list any
        # earlier would miss the draft this very run just produced.
        sar_by_investigation: dict = {}
        try:
            sars = client.get(base + SAR_LIST_PATH, params={"limit": 100}, timeout=30)
            sars.raise_for_status()
            for s in sars.json():
                inv_id = s.get("investigation_id")
                if inv_id and (inv_id not in sar_by_investigation
                               or s.get("created_at", "") >= sar_by_investigation[inv_id].get("created_at", "")):
                    sar_by_investigation[inv_id] = s
        except Exception as exc:
            state["errors"].append({"id": "_sar_list", "error": str(exc)})

        state.update(outcomes=outcomes, latencies=latencies, errored_ids=errored_ids,
                     sar_by_investigation=sar_by_investigation)
        availability = 1.0 - (len(errored_ids) / len(entries) if entries else 0.0)
        return CheckResult(check_id="availability", suite="sentinel",
                           score_type="deterministic", value=round(availability, 4),
                           passed=availability >= 0.95, traces={"errors": state["errors"]})

    def typology_accuracy() -> CheckResult:
        hits, misses = 0, []
        for sid, (detail, e) in state["outcomes"].items():
            if detail is None:
                misses.append({"id": sid, "expected": e["expected_typology"], "got": None, "reason": "errored"})
                continue
            detected = _detected_typologies(detail)
            if _typology_hit(e["expected_typology"], detected):
                hits += 1
            else:
                misses.append({"id": sid, "expected": e["expected_typology"], "got": sorted(detected)})
        n = len(state["outcomes"]) or 1
        score = hits / n
        return CheckResult(check_id="typology_accuracy", suite="sentinel",
                           score_type="deterministic", value=round(score, 4),
                           passed=score >= 0.75,
                           traces={"misses": misses, "errored": state["errored_ids"]})

    def pipeline_completion_rate() -> CheckResult:
        rates = []
        for sid, (detail, e) in state["outcomes"].items():
            if detail is None:
                rates.append(0.0)
            else:
                rates.append(_clean_finding_count(detail) / len(EXPECTED_AGENT_TYPES))
        score = sum(rates) / len(rates) if rates else 0.0
        return CheckResult(check_id="pipeline_completion_rate", suite="sentinel",
                           score_type="deterministic", value=round(score, 4),
                           passed=score >= 0.8,
                           traces={"note": "clean = Finding.evidence has no 'error' key; "
                                           "fallback/degraded agent runs count as incomplete",
                                   "errored": state["errored_ids"]})

    def sar_schema_validity() -> CheckResult:
        ok, bad, not_applicable = 0, [], []
        applicable = 0
        for sid, (detail, e) in state["outcomes"].items():
            if detail is None:
                applicable += 1
                bad.append({"id": sid, "missing": sorted(SAR_REQUIRED_FIELDS), "reason": "errored"})
                continue
            if detail.get("status") != "completed":
                not_applicable.append({"id": sid, "status": detail.get("status")})
                continue
            applicable += 1
            sar = state["sar_by_investigation"].get(detail.get("_investigation_id"))
            missing = _sar_missing_fields(sar)
            if not missing:
                ok += 1
            else:
                bad.append({"id": sid, "missing": missing})
        score = ok / applicable if applicable else 0.0
        return CheckResult(check_id="sar_schema_validity", suite="sentinel",
                           score_type="deterministic", value=round(score, 4),
                           passed=(score == 1.0 and applicable > 0),
                           traces={"bad": bad, "not_applicable": not_applicable,
                                   "errored": state["errored_ids"]})

    def latency() -> CheckResult:
        v = p95(state["latencies"])
        passed = (v < 120000) and not state.get("errors") and bool(state["latencies"])
        return CheckResult(check_id="p95_latency_ms", suite="sentinel",
                           score_type="deterministic", value=round(v, 1),
                           passed=passed, traces={"n": len(state["latencies"]),
                                                  "errored_queries": len(state.get("errors", []))})

    return Suite(name="sentinel", checks=[
        Check(id="availability", suite="sentinel", description="gather: trigger + poll all 8 seeded investigations", fn=gather),
        Check(id="typology_accuracy", suite="sentinel", description="detected typology matches seeded scenario", fn=typology_accuracy),
        Check(id="pipeline_completion_rate", suite="sentinel", description="full LLM path vs fallback (evidence.error-free findings / 5 expected agents)", fn=pipeline_completion_rate),
        Check(id="sar_schema_validity", suite="sentinel", description="SAR drafts have required fields, read-only via GET /api/v1/sar/", fn=sar_schema_validity),
        Check(id="p95_latency_ms", suite="sentinel", description="p95 end-to-end run-trigger-to-completed latency", fn=latency),
    ])
