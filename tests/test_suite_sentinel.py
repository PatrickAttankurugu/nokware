import time
from datetime import datetime, timedelta, timezone

import pytest
from pytest_httpx import HTTPXMock

import suites.sentinel as sentinel_mod
from suites.sentinel import build_suite


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)


def alerts_response(scenarios: dict[str, str]):
    """scenarios: {alert_id: scenario}"""
    return {"alerts": [{"id": aid, "raw_data": {"scenario": s}} for aid, s in scenarios.items()],
            "total": len(scenarios)}


def investigations_response(links: dict[str, str]):
    """links: {investigation_id: alert_id}"""
    return {"investigations": [{"id": iid, "alert_id": aid} for iid, aid in links.items()],
            "total": len(links)}


def sar_response(entries: list[dict]):
    return entries


def finding(agent_type, error=None, created_at=None):
    """created_at defaults to "now" so a finding registers as belonging to *this*
    gather() run's trigger_time under the staleness cutoff (suites/sentinel.py
    GRACE_MARGIN_S); pass an explicit older timestamp to simulate a stale leftover
    from a previous run."""
    ev = {"error": error} if error else {}
    ts = created_at if created_at is not None else datetime.now(timezone.utc).isoformat()
    return {"agent_type": agent_type, "finding_type": f"{agent_type}_report", "evidence": ev,
            "created_at": ts}


def clean_findings():
    """Freshly-timestamped each call (see finding() docstring) -- a module-level constant
    built once at import time would go stale relative to gather()'s trigger_time in a slow
    test run."""
    return [finding("research"), finding("document_analysis"), finding("regulatory"),
            finding("network_analysis"), finding("risk_assessment")]


def detail_response(status, typologies=None, findings=None):
    return {
        "status": status,
        "findings_summary": {"typologies_detected": typologies or []} if typologies is not None else None,
        "findings": findings if findings is not None else [],
    }


def write_golden(tmp_path, lines):
    p = tmp_path / "g.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_sentinel_suite_scores_happy_path(httpx_mock: HTTPXMock, tmp_path):
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})  # POST run
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], clean_findings()))
    httpx_mock.add_response(json=sar_response([
        {"investigation_id": "inv-1", "narrative": "SAR narrative", "risk_indicators": ["x"],
         "status": "draft", "created_at": "2026-07-16T00:00:00Z"}
    ]))  # GET SAR list, fetched only after every scenario has been triggered + polled

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["availability"].value == 1.0
    assert results["typology_accuracy"].value == 1.0
    assert results["pipeline_completion_rate"].value == 1.0
    assert results["sar_schema_validity"].value == 1.0
    assert results["sar_schema_validity"].passed
    assert results["p95_latency_ms"].passed


def test_sentinel_suite_flags_typology_miss(httpx_mock: HTTPXMock, tmp_path):
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("completed", ["layering"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["typology_accuracy"].value == 0.0
    assert results["typology_accuracy"].passed is False
    assert results["typology_accuracy"].traces["misses"][0]["expected"] == "structuring"


def test_sentinel_suite_unusual_volume_alias(httpx_mock: HTTPXMock, tmp_path):
    """network_analysis reports 'velocity_anomaly' for the seeder's 'unusual_volume' scenario."""
    golden = write_golden(tmp_path, [
        '{"id": "unusual_volume-01", "scenario": "unusual_volume", "expected_typology": "unusual_volume"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "unusual_volume"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("closed", ["velocity_anomaly"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["typology_accuracy"].value == 1.0


def test_sentinel_suite_pep_and_sanctions_from_watchlist_hits(httpx_mock: HTTPXMock, tmp_path):
    """pep_screening / sanctions_match never appear in typologies_detected -- they come from
    the research agent's local_watchlist_check.pep_hits / sanctions_hits."""
    golden = write_golden(tmp_path, [
        '{"id": "pep-01", "scenario": "pep_screening", "expected_typology": "pep_screening"}',
        '{"id": "sanctions-01", "scenario": "sanctions_match", "expected_typology": "sanctions_match"}',
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "pep_screening", "alert-2": "sanctions_match"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1", "inv-2": "alert-2"}))

    research_pep = finding("research")
    research_pep["evidence"] = {"local_watchlist_check": {"pep_hits": ["hit"], "sanctions_hits": []}}
    findings_pep = [research_pep] + clean_findings()[1:]

    research_sanctions = finding("research")
    research_sanctions["evidence"] = {"local_watchlist_check": {"pep_hits": [], "sanctions_hits": ["hit"]}}
    findings_sanctions = [research_sanctions] + clean_findings()[1:]

    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("escalated", [], findings_pep))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-2"})
    httpx_mock.add_response(json=detail_response("completed", [], findings_sanctions))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["typology_accuracy"].value == 1.0


def test_sentinel_suite_pipeline_completion_reflects_fallback(httpx_mock: HTTPXMock, tmp_path):
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    degraded = [finding("research", error="llm_unavailable"), finding("document_analysis"),
                finding("regulatory", error="llm_unavailable"), finding("network_analysis"),
                finding("risk_assessment")]
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], degraded))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["pipeline_completion_rate"].value == 0.6  # 3 of 5 agents clean
    assert results["pipeline_completion_rate"].passed is False


def test_sentinel_suite_dedupes_findings_accumulated_across_reruns(httpx_mock: HTTPXMock, tmp_path):
    """SENTINEL never deletes old Finding rows: since this suite re-triggers /run every
    night, a long-lived seeded investigation accumulates multiple rows per agent_type
    over time. Only the most recent row per agent should count, so completion never
    exceeds 1.0 and a stale watchlist hit from an earlier run can't leak into today's
    typology_accuracy."""
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    # two rounds of findings for every agent (an older errored round from a previous
    # night, then a clean one from this run) -- server orders by created_at ascending,
    # so the clean round is last per agent_type, and the older round genuinely predates
    # this run's trigger time so it is also excluded outright as stale.
    previous_night = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    stale_round = [finding(a, error="llm_unavailable", created_at=previous_night) for a in
                   ["research", "document_analysis", "regulatory", "network_analysis", "risk_assessment"]]
    accumulated = stale_round + clean_findings()
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], accumulated))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["pipeline_completion_rate"].value == 1.0  # not 2.0
    stale_excluded = results["pipeline_completion_rate"].traces["stale_findings_excluded"]
    assert len(stale_excluded[0]["stale"]) == 5  # the whole previous-night round


def test_sentinel_suite_sar_not_applicable_when_not_completed(httpx_mock: HTTPXMock, tmp_path):
    golden = write_golden(tmp_path, [
        '{"id": "unusual_volume-01", "scenario": "unusual_volume", "expected_typology": "unusual_volume"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "unusual_volume"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("closed", ["velocity_anomaly"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    sar_result = results["sar_schema_validity"]
    assert sar_result.traces["not_applicable"] == [{"id": "unusual_volume-01", "status": "closed"}]
    # zero applicable scenarios is not a vacuous pass
    assert sar_result.value == 0.0
    assert sar_result.passed is False


def test_sentinel_suite_handles_full_outage(httpx_mock: HTTPXMock, tmp_path):
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}',
        '{"id": "layering-01", "scenario": "layering", "expected_typology": "layering"}',
    ])
    httpx_mock.add_response(status_code=500)  # GET alerts fails -> everything is a forced miss

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["availability"].value == 0.0
    assert results["availability"].passed is False
    assert results["typology_accuracy"].value == 0.0
    assert results["typology_precision"].value == 0.0
    assert results["typology_precision"].passed is False
    assert set(results["typology_precision"].traces["errored"]) == {"structuring-01", "layering-01"}
    assert results["pipeline_completion_rate"].value == 0.0
    assert results["sar_schema_validity"].passed is False
    assert results["p95_latency_ms"].passed is False


def test_sentinel_suite_per_scenario_error_is_forced_miss(httpx_mock: HTTPXMock, tmp_path):
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}',
        '{"id": "layering-01", "scenario": "layering", "expected_typology": "layering"}',
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring", "alert-2": "layering"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1", "inv-2": "alert-2"}))
    httpx_mock.add_response(status_code=500)  # POST run fails for structuring
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-2"})
    httpx_mock.add_response(json=detail_response("completed", ["layering"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["availability"].value == 0.5
    assert results["availability"].traces["errors"][0]["id"] == "structuring-01"
    assert results["typology_accuracy"].value == 0.5  # 1 hit (layering) out of 2


def test_sentinel_suite_poll_timeout_is_forced_miss(httpx_mock: HTTPXMock, tmp_path, monkeypatch):
    monkeypatch.setattr(sentinel_mod, "MAX_POLLS", 2)
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("in_progress"))
    httpx_mock.add_response(json=detail_response("in_progress"))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["availability"].value == 0.0
    assert "still 'in_progress'" in results["availability"].traces["errors"][0]["error"]
    assert results["typology_precision"].value == 0.0
    assert results["typology_precision"].traces["errored"] == ["structuring-01"]


def test_sentinel_suite_duplicate_alerts_newest_wins(httpx_mock: HTTPXMock, tmp_path):
    """Two alerts share the same scenario label (e.g. a reseed left an old row behind) --
    resolution must pick the alert with the newest created_at, not whichever the API lists
    last. alert-old is listed last on purpose: an order-trusting dict comprehension would
    pick it, but only alert-new has a linked investigation, so picking wrong would surface
    as a forced miss."""
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json={"alerts": [
        {"id": "alert-new", "raw_data": {"scenario": "structuring"}, "created_at": "2026-07-15T00:00:00Z"},
        {"id": "alert-old", "raw_data": {"scenario": "structuring"}, "created_at": "2026-07-01T00:00:00Z"},
    ], "total": 2})
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-new"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["availability"].value == 1.0
    dupes = results["availability"].traces["duplicate_mappings"]
    assert any(d["scenario"] == "structuring" and d["chosen_id"] == "alert-new"
               and d["discarded_ids"] == ["alert-old"] for d in dupes)


def test_sentinel_suite_duplicate_investigations_newest_wins(httpx_mock: HTTPXMock, tmp_path):
    """Two investigations link back to the same alert -- resolution must pick the one with
    the newest created_at. inv-old is listed last on purpose to catch an order-trusting
    dict comprehension silently picking it instead."""
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring"}))
    httpx_mock.add_response(json={"investigations": [
        {"id": "inv-new", "alert_id": "alert-1", "created_at": "2026-07-15T00:00:00Z"},
        {"id": "inv-old", "alert_id": "alert-1", "created_at": "2026-07-01T00:00:00Z"},
    ], "total": 2})
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-new"})
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["availability"].value == 1.0
    dupes = results["availability"].traces["duplicate_mappings"]
    assert any(d["alert_id"] == "alert-1" and d["chosen_id"] == "inv-new"
               and d["discarded_ids"] == ["inv-old"] for d in dupes)


def test_sentinel_suite_alert_without_investigation_is_forced_miss(httpx_mock: HTTPXMock, tmp_path):
    """An alert with no linked investigation (yet) must force-miss only its own scenario,
    not raise out of gather() and take the whole run down with it."""
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}',
        '{"id": "layering-01", "scenario": "layering", "expected_typology": "layering"}',
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring", "alert-2": "layering"}))
    # only alert-2 (layering) has a linked investigation; alert-1 (structuring) has none
    httpx_mock.add_response(json=investigations_response({"inv-2": "alert-2"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-2"})
    httpx_mock.add_response(json=detail_response("completed", ["layering"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["availability"].value == 0.5
    errors = results["availability"].traces["errors"]
    assert any(e["id"] == "structuring-01" and "no investigation linked" in e["error"] for e in errors)
    assert results["typology_accuracy"].value == 0.5  # layering is unaffected


def test_sentinel_suite_stale_findings_excluded_from_completion_rate(httpx_mock: HTTPXMock, tmp_path):
    """Regression for the staleness-leak finding: a rerun writes fresh findings for only 2
    of 5 agents; 3 rows survive from a previous night's run (one of them missing created_at
    entirely, which must be treated defensively as stale too). completion rate must reflect
    2/5 (0.4), not count the stale rows as if they belonged to this run."""
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    previous_night = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    # a row with no created_at at all -- must be treated defensively as stale, not clean
    missing_created_at = finding("risk_assessment")
    del missing_created_at["created_at"]
    stale_findings = [
        finding("regulatory", created_at=previous_night),
        finding("network_analysis", created_at=previous_night),
        missing_created_at,
    ]
    fresh_findings = [finding("research"), finding("document_analysis")]
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], stale_findings + fresh_findings))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["pipeline_completion_rate"].value == 0.4
    stale_excluded = results["pipeline_completion_rate"].traces["stale_findings_excluded"]
    assert len(stale_excluded[0]["stale"]) == 3


def test_sentinel_suite_typology_precision_drops_with_overtriggering(httpx_mock: HTTPXMock, tmp_path):
    """A network agent that fires 'layering' on every scenario regardless of ground truth
    keeps accuracy high (the expected label is always present in the detected set) but must
    tank precision, since only half of what it reports is ever right."""
    golden = write_golden(tmp_path, [
        '{"id": "structuring-01", "scenario": "structuring", "expected_typology": "structuring"}',
        '{"id": "round_tripping-01", "scenario": "round_tripping", "expected_typology": "round_tripping"}',
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "structuring", "alert-2": "round_tripping"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1", "inv-2": "alert-2"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("completed", ["structuring", "layering"], clean_findings()))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-2"})
    httpx_mock.add_response(json=detail_response("completed", ["round_tripping", "layering"], clean_findings()))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["typology_accuracy"].value == 1.0
    assert results["typology_precision"].value == 0.5  # 1 correct / 2 detected, both scenarios
    assert results["typology_precision"].passed is False
    spurious = results["typology_precision"].traces["per_scenario"]["structuring-01"]["spurious"]
    assert spurious == ["layering"]
