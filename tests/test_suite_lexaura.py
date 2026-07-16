import time

import pytest
from pytest_httpx import HTTPXMock

from nokware.judge import Judge
from nokware.runner import JudgeBudget
from suites.lexaura import build_suite


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_args, **_kwargs: None)


def fake_response(answer, snippets, titles, must_cite="s.4"):
    return {
        "answer": answer,
        "sources": [
            {
                "title": t,
                "body": "Some Regulatory Body",
                "country": "Ghana",
                "year": 2020,
                "snippet": s,
                "relevance_score": 0.9,
                "provenance": "official_document",
            }
            for s, t in zip(snippets, titles)
        ],
        "category": "KYC",
        "grounding": None,
    }


def test_lexaura_suite_scores(httpx_mock: HTTPXMock, tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "q1", "question": "What is the fee?", '
        '"source_quote": "a registration fee of 500 cedis", "must_cite": "s.4", '
        '"jurisdiction": "ghana"}\n'
    )
    httpx_mock.add_response(json=fake_response(
        "The registration fee is 500 cedis (s.4).",
        ["Applicants must pay a registration fee of 500 cedis."],
        ["Registration Directive s.4"],
    ))
    judge = Judge(api_key=None, budget=JudgeBudget(limit=10))
    suite = build_suite("https://lex.example.com", judge, golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["availability"].value == 1.0
    assert results["retrieval_hit_rate"].value == 1.0
    assert results["citation_integrity"].value == 1.0
    assert results["faithfulness"].score_type == "llm_judge"
    assert results["faithfulness"].traces["engines"] == {"gemini": 0, "fallback": 1}
    assert results["p95_latency_ms"].passed


def test_lexaura_suite_flags_misses(httpx_mock: HTTPXMock, tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "q1", "question": "What is the fee?", '
        '"source_quote": "a registration fee of 500 cedis", "must_cite": "s.4", '
        '"jurisdiction": "ghana"}\n'
    )
    httpx_mock.add_response(json=fake_response(
        "I could not find this information.",
        ["Unrelated content about something else entirely."],
        ["Unrelated Directive"],
    ))
    judge = Judge(api_key=None, budget=JudgeBudget(limit=10))
    suite = build_suite("https://lex.example.com", judge, golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["retrieval_hit_rate"].value == 0.0
    assert results["retrieval_hit_rate"].passed is False
    assert results["citation_integrity"].value == 0.0
    assert results["citation_integrity"].passed is False


def test_lexaura_suite_handles_errors(httpx_mock: HTTPXMock, tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "q1", "question": "What is the fee?", '
        '"source_quote": "a registration fee of 500 cedis", "must_cite": "s.4", '
        '"jurisdiction": "ghana"}\n'
        '{"id": "q2", "question": "What is the penalty?", '
        '"source_quote": "up to 5 years imprisonment", "must_cite": "s.9", '
        '"jurisdiction": "nigeria"}\n'
    )
    httpx_mock.add_response(status_code=404)
    httpx_mock.add_response(status_code=503)
    judge = Judge(api_key=None, budget=JudgeBudget(limit=10))
    suite = build_suite("https://lex.example.com", judge, golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["availability"].value == 0.0
    assert results["availability"].passed is False


def test_lexaura_suite_fails_checks_under_full_outage(httpx_mock: HTTPXMock, tmp_path):
    golden = tmp_path / "g.jsonl"
    golden.write_text(
        '{"id": "q1", "question": "What is the fee?", '
        '"source_quote": "a registration fee of 500 cedis", "must_cite": "s.4", '
        '"jurisdiction": "ghana"}\n'
        '{"id": "q2", "question": "What is the penalty?", '
        '"source_quote": "up to 5 years imprisonment", "must_cite": "s.9", '
        '"jurisdiction": "nigeria"}\n'
    )
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=500)
    judge = Judge(api_key=None, budget=JudgeBudget(limit=10))
    suite = build_suite("https://lex.example.com", judge, golden_path=str(golden))
    results = {r.check_id: r for r in suite.run()}
    assert results["p95_latency_ms"].passed is False
    assert results["retrieval_hit_rate"].passed is False
    assert results["citation_integrity"].passed is False
    assert results["faithfulness"].passed is False
    assert results["availability"].passed is False
