import json
import time
from datetime import datetime, timedelta, timezone

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

# Findings (and alert/investigation rows) can legitimately be written a moment before we
# capture "now" on this host, and this host's clock is not the SENTINEL server's clock --
# so a staleness/resolution cutoff compares against (trigger time - GRACE_MARGIN_S), not
# the raw trigger time, to absorb ordinary clock skew without misclassifying a fresh row.
GRACE_MARGIN_S = 120

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


def _parse_iso(ts) -> "datetime | None":
    """Best-effort ISO-8601 parse. Missing/unparseable timestamps return None so callers
    can treat them defensively (never let an unparseable timestamp win a "newest" contest,
    and treat it as stale under a staleness cutoff)."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _resolve_latest_by_key(items: list[dict], key_fn, id_fn, created_fn, key_label: str):
    """Group items by key_fn(item) and keep only the one with the newest created_at per
    key, instead of trusting API response order (the last item in a dict comprehension
    silently winning is not a resolution strategy). A missing/unparseable created_at never
    outranks a parsed one. Ties (or all-unparseable groups) keep the last item in response
    order, matching the previous (order-trusting) behavior as the final fallback only when
    there is truly no timestamp evidence to prefer one row over another.

    Returns (resolved: {key: id}, duplicates: [{key_label: key, chosen_id, discarded_ids}])
    for any key that had more than one candidate, for gather traces."""
    groups: dict = {}
    for item in items:
        key = key_fn(item)
        if key is None:
            continue
        groups.setdefault(key, []).append(item)

    def sort_key(item):
        dt = _parse_iso(created_fn(item))
        return dt if dt is not None else datetime.min.replace(tzinfo=timezone.utc)

    resolved: dict = {}
    duplicates: list = []
    for key, group in groups.items():
        if len(group) == 1:
            resolved[key] = id_fn(group[0])
            continue
        ordered = sorted(group, key=sort_key)
        chosen = ordered[-1]
        resolved[key] = id_fn(chosen)
        duplicates.append({
            key_label: key,
            "chosen_id": id_fn(chosen),
            "discarded_ids": [id_fn(it) for it in ordered[:-1]],
        })
    return resolved, duplicates


def _latest_findings_by_agent(detail: dict, trigger_time: "datetime | None" = None):
    """SENTINEL never dedupes Finding rows: POST /run on an already-run investigation
    (which this suite does every night) appends a fresh Finding per agent rather than
    replacing the old one, so a long-lived seeded investigation accumulates multiple
    rows per agent_type over time. Keep only the row with the newest created_at per
    agent_type -- dedup by timestamp, not by list position/order -- otherwise
    clean-finding counts and typology detection would double count history and could
    exceed the 1.0 ceiling after enough nightly reruns.

    If trigger_time is given, any finding whose created_at predates
    (trigger_time - GRACE_MARGIN_S) is leftover from a previous run, not this run's
    output: it is excluded entirely (not just deduped) and reported back as stale.
    A missing/unparseable created_at is treated defensively as stale in that case, since
    there is no evidence it belongs to this run.

    Returns (latest: {agent_type: finding}, stale: [{"agent_type", "created_at"}])."""
    cutoff = (trigger_time - timedelta(seconds=GRACE_MARGIN_S)) if trigger_time is not None else None
    latest: dict = {}
    stale: list = []
    for f in detail.get("findings", []):
        agent = f.get("agent_type")
        if not agent:
            continue
        created = _parse_iso(f.get("created_at"))
        if cutoff is not None and (created is None or created < cutoff):
            stale.append({"agent_type": agent, "created_at": f.get("created_at")})
            continue
        existing = latest.get(agent)
        if existing is not None:
            existing_created = _parse_iso(existing.get("created_at"))
            # keep existing unless the new row is a strictly newer, parsed timestamp
            if existing_created is not None and (created is None or created < existing_created):
                continue
        latest[agent] = f
    return latest, stale


def _detected_typologies(detail: dict, trigger_time: "datetime | None" = None):
    fs = detail.get("findings_summary") or {}
    detected = {str(t).lower() for t in fs.get("typologies_detected", []) if t}
    latest_by_agent, stale = _latest_findings_by_agent(detail, trigger_time)
    research = latest_by_agent.get("research")
    if research:
        watchlist = (research.get("evidence") or {}).get("local_watchlist_check") or {}
        if watchlist.get("pep_hits"):
            detected.add("pep_screening")
        if watchlist.get("sanctions_hits"):
            detected.add("sanctions_match")
    return detected, stale


def _typology_hit(expected: str, detected: set[str]) -> bool:
    aliases = TYPOLOGY_ALIASES.get(expected, {expected})
    return bool(aliases & detected)


def _clean_finding_count(detail: dict, trigger_time: "datetime | None" = None):
    """Count of expected agents (out of EXPECTED_AGENT_TYPES) whose most recent,
    non-stale Finding carries no evidence.error -- an errored/fallback agent still
    writes a Finding row (see discovery note above), so absence of a Finding row is
    not the fallback signal; the per-finding evidence.error field is.

    Returns (count, stale) where stale is the list of findings excluded as leftover
    from a previous run (see _latest_findings_by_agent)."""
    latest, stale = _latest_findings_by_agent(detail, trigger_time)
    count = sum(
        1 for agent in EXPECTED_AGENT_TYPES
        if agent in latest and not (latest[agent].get("evidence") or {}).get("error")
    )
    return count, stale


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

        duplicate_mappings: list = []
        try:
            alerts = client.get(base + ALERTS_PATH, params={"limit": 100}, timeout=30)
            alerts.raise_for_status()
            scenario_to_alert, scenario_dupes = _resolve_latest_by_key(
                alerts.json().get("alerts", []),
                key_fn=lambda a: (a.get("raw_data") or {}).get("scenario"),
                id_fn=lambda a: a["id"],
                created_fn=lambda a: a.get("created_at"),
                key_label="scenario",
            )
            invs = client.get(base + INVESTIGATIONS_LIST_PATH, params={"limit": 100}, timeout=30)
            invs.raise_for_status()
            alert_to_investigation, alert_dupes = _resolve_latest_by_key(
                invs.json().get("investigations", []),
                key_fn=lambda i: i.get("alert_id"),
                id_fn=lambda i: i["id"],
                created_fn=lambda i: i.get("created_at"),
                key_label="alert_id",
            )
            duplicate_mappings = scenario_dupes + alert_dupes
        except Exception as exc:
            for e in entries:
                state["errors"].append({"id": e["id"], "error": str(exc)})
                errored_ids.append(e["id"])
                outcomes[e["id"]] = (None, e)
            state.update(outcomes=outcomes, latencies=[], errored_ids=errored_ids, sar_by_investigation={},
                         trigger_times={})
            return CheckResult(check_id="availability", suite="sentinel",
                               score_type="deterministic", value=0.0, passed=False,
                               traces={"errors": state["errors"]})

        trigger_times: dict = {}
        for e in entries:
            t0 = time.monotonic()
            try:
                alert_id = scenario_to_alert.get(e["scenario"])
                if alert_id is None:
                    raise ValueError(f"no live alert for scenario {e['scenario']!r}")
                investigation_id = alert_to_investigation.get(alert_id)
                if investigation_id is None:
                    raise ValueError(f"no investigation linked to alert {alert_id}")
                trigger_times[e["id"]] = datetime.now(timezone.utc)
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
                     sar_by_investigation=sar_by_investigation, trigger_times=trigger_times)
        availability = 1.0 - (len(errored_ids) / len(entries) if entries else 0.0)
        return CheckResult(check_id="availability", suite="sentinel",
                           score_type="deterministic", value=round(availability, 4),
                           passed=availability >= 0.95,
                           traces={"errors": state["errors"], "duplicate_mappings": duplicate_mappings})

    def typology_accuracy() -> CheckResult:
        hits, misses = 0, []
        stale_findings_excluded = []
        for sid, (detail, e) in state["outcomes"].items():
            if detail is None:
                misses.append({"id": sid, "expected": e["expected_typology"], "got": None, "reason": "errored"})
                continue
            trigger_time = state.get("trigger_times", {}).get(sid)
            detected, stale = _detected_typologies(detail, trigger_time)
            if stale:
                stale_findings_excluded.append({"id": sid, "stale": stale})
            if _typology_hit(e["expected_typology"], detected):
                hits += 1
            else:
                misses.append({"id": sid, "expected": e["expected_typology"], "got": sorted(detected)})
        n = len(state["outcomes"]) or 1
        score = hits / n
        return CheckResult(check_id="typology_accuracy", suite="sentinel",
                           score_type="deterministic", value=round(score, 4),
                           passed=score >= 0.85,
                           traces={"misses": misses, "errored": state["errored_ids"],
                                   "stale_findings_excluded": stale_findings_excluded})

    def pipeline_completion_rate() -> CheckResult:
        rates = []
        stale_findings_excluded = []
        for sid, (detail, e) in state["outcomes"].items():
            if detail is None:
                rates.append(0.0)
            else:
                trigger_time = state.get("trigger_times", {}).get(sid)
                count, stale = _clean_finding_count(detail, trigger_time)
                if stale:
                    stale_findings_excluded.append({"id": sid, "stale": stale})
                rates.append(count / len(EXPECTED_AGENT_TYPES))
        score = sum(rates) / len(rates) if rates else 0.0
        return CheckResult(check_id="pipeline_completion_rate", suite="sentinel",
                           score_type="deterministic", value=round(score, 4),
                           passed=score >= 0.8,
                           traces={"note": "clean = Finding.evidence has no 'error' key; "
                                           "fallback/degraded agent runs count as incomplete",
                                   "errored": state["errored_ids"],
                                   "stale_findings_excluded": stale_findings_excluded})

    def typology_precision() -> CheckResult:
        """Precision counterpart to typology_accuracy: accuracy only asks whether the
        expected label is somewhere in the detected set, so an agent that fires every
        typology on every scenario would score a perfect 1.0 there while being useless.
        Per scenario: |{expected} ∩ detected| / |detected| (via the same alias rule as
        _typology_hit); an empty detected set contributes 0.0 rather than being excluded,
        since "detected nothing" is not neutral for a check about over-triggering."""
        scores = []
        per_scenario: dict = {}
        errored = []
        for sid, (detail, e) in state["outcomes"].items():
            expected = e["expected_typology"]
            if detail is None:
                scores.append(0.0)
                errored.append(sid)
                continue
            trigger_time = state.get("trigger_times", {}).get(sid)
            detected, _stale = _detected_typologies(detail, trigger_time)
            aliases = TYPOLOGY_ALIASES.get(expected, {expected})
            spurious = sorted(detected - aliases)
            if not detected:
                scores.append(0.0)
            else:
                numerator = 1 if _typology_hit(expected, detected) else 0
                scores.append(numerator / len(detected))
            per_scenario[sid] = {"expected": expected, "detected": sorted(detected), "spurious": spurious}
        score = sum(scores) / len(scores) if scores else 0.0
        return CheckResult(check_id="typology_precision", suite="sentinel",
                           score_type="deterministic", value=round(score, 4),
                           passed=score >= 0.6,
                           traces={"per_scenario": per_scenario, "errored": errored})

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
        Check(id="typology_precision", suite="sentinel", description="detected typologies aren't over-triggered noise (precision vs. expected label)", fn=typology_precision),
        Check(id="pipeline_completion_rate", suite="sentinel", description="full LLM path vs fallback (evidence.error-free findings / 5 expected agents)", fn=pipeline_completion_rate),
        Check(id="sar_schema_validity", suite="sentinel", description="SAR drafts have required fields, read-only via GET /api/v1/sar/", fn=sar_schema_validity),
        Check(id="p95_latency_ms", suite="sentinel", description="p95 end-to-end run-trigger-to-completed latency", fn=latency),
    ])
