import httpx
import pytest
from pytest_httpx import HTTPXMock

from suites.africapep import build_suite


def fake_response(names):
    return {"results": [{"full_name": n} for n in names]}


def test_suite_scores_from_recorded_responses(httpx_mock: HTTPXMock, tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "p1", "kind": "positive", "query": "John Mahama", "country": "GH", '
        '"expect_name": "John Mahama", "max_rank": 1}\n'
        '{"id": "n1", "kind": "negative", "query": "Random Person", "country": "GH"}\n'
    )
    httpx_mock.add_response(json=fake_response(["John Mahama", "John Mahama Jr"]))
    httpx_mock.add_response(json=fake_response([]))
    suite = build_suite("https://api.example.com", "k", golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["precision_at_5"].passed
    assert results["negative_controls"].value == 1.0
    assert results["availability"].value == 1.0
