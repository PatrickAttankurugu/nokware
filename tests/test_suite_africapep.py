import httpx
import pytest
from pytest_httpx import HTTPXMock

from suites.africapep import build_suite


def fake_response(items):
    """items: list of (id, full_name) tuples."""
    return {"results": [{"id": i, "full_name": n} for i, n in items]}


def test_suite_scores_from_recorded_responses(httpx_mock: HTTPXMock, tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "p1", "kind": "positive", "query": "John Mahama", "country": "GH", '
        '"expect_name": "John Mahama", "expect_qid": "wd:Q50678", "max_rank": 1}\n'
        '{"id": "n1", "kind": "negative", "query": "Random Person", "country": "GH"}\n'
    )
    httpx_mock.add_response(json=fake_response([("wd:Q50678", "John Mahama")]))
    httpx_mock.add_response(json=fake_response([]))
    suite = build_suite("https://api.example.com", "k", golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["precision_at_5"].passed
    assert results["negative_controls"].value == 1.0
    assert results["availability"].value == 1.0


def test_suite_matches_on_qid_not_name_substring(httpx_mock: HTTPXMock, tmp_path):
    """A same-named but different person (different QID) must not count as
    relevant, and the correct QID must count even if ranked below a
    same-named decoy. This is the identity-based matching contract."""
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "p1", "kind": "positive", "query": "Ibrahim Traore", "country": "BF", '
        '"expect_name": "Ibrahim Traore", "expect_qid": "wd:Q114341246", "max_rank": 2}\n'
    )
    # decoy (different person, same name) ranked first, correct QID ranked second
    httpx_mock.add_response(json=fake_response([
        ("wd:Q134717793", "Ibrahim Traore"), ("wd:Q114341246", "Ibrahim Traore"),
    ]))
    suite = build_suite("https://api.example.com", "k", golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["mrr"].value == 0.5
    assert results["precision_at_5"].value == 0.5


def test_suite_falls_back_to_name_substring_without_qid(httpx_mock: HTTPXMock, tmp_path):
    """Entries with no expect_qid (legacy shape) still match by name."""
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "p1", "kind": "positive", "query": "John Mahama", "country": "GH", '
        '"expect_name": "John Mahama", "max_rank": 1}\n'
    )
    httpx_mock.add_response(json=fake_response([("wd:Q50678", "John Mahama")]))
    suite = build_suite("https://api.example.com", "k", golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["precision_at_5"].passed


def test_suite_fails_checks_under_full_outage(httpx_mock: HTTPXMock, tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "p1", "kind": "positive", "query": "John Mahama", "country": "GH", '
        '"expect_name": "John Mahama", "expect_qid": "wd:Q50678", "max_rank": 1}\n'
        '{"id": "n1", "kind": "negative", "query": "Random Person", "country": "GH"}\n'
    )
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=500)
    suite = build_suite("https://api.example.com", "k", golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["p95_latency_ms"].passed is False
    assert results["negative_controls"].passed is False
    assert results["availability"].passed is False
