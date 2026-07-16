import time

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


def finding(agent_type, error=None):
    ev = {"error": error} if error else {}
    return {"agent_type": agent_type, "finding_type": f"{agent_type}_report", "evidence": ev}


CLEAN_FINDINGS = [finding("research"), finding("document_analysis"), finding("regulatory"),
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
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], CLEAN_FINDINGS))
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
    httpx_mock.add_response(json=detail_response("completed", ["layering"], CLEAN_FINDINGS))
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
    httpx_mock.add_response(json=detail_response("closed", ["velocity_anomaly"], CLEAN_FINDINGS))
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
    findings_pep = [research_pep] + CLEAN_FINDINGS[1:]

    research_sanctions = finding("research")
    research_sanctions["evidence"] = {"local_watchlist_check": {"pep_hits": [], "sanctions_hits": ["hit"]}}
    findings_sanctions = [research_sanctions] + CLEAN_FINDINGS[1:]

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
    # two rounds of findings for every agent (an older errored round, then a clean one) --
    # server orders by created_at ascending, so the clean round is last per agent_type.
    stale_round = [finding(a, error="llm_unavailable") for a in
                   ["research", "document_analysis", "regulatory", "network_analysis", "risk_assessment"]]
    accumulated = stale_round + CLEAN_FINDINGS
    httpx_mock.add_response(json=detail_response("completed", ["structuring"], accumulated))
    httpx_mock.add_response(json=sar_response([]))

    suite = build_suite("https://sentinel.example.com", golden_path=golden)
    results = {r.check_id: r for r in suite.run()}

    assert results["pipeline_completion_rate"].value == 1.0  # not 2.0


def test_sentinel_suite_sar_not_applicable_when_not_completed(httpx_mock: HTTPXMock, tmp_path):
    golden = write_golden(tmp_path, [
        '{"id": "unusual_volume-01", "scenario": "unusual_volume", "expected_typology": "unusual_volume"}'
    ])
    httpx_mock.add_response(json=alerts_response({"alert-1": "unusual_volume"}))
    httpx_mock.add_response(json=investigations_response({"inv-1": "alert-1"}))
    httpx_mock.add_response(json={"status": "running", "investigation_id": "inv-1"})
    httpx_mock.add_response(json=detail_response("closed", ["velocity_anomaly"], CLEAN_FINDINGS))
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
    httpx_mock.add_response(json=detail_response("completed", ["layering"], CLEAN_FINDINGS))
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
