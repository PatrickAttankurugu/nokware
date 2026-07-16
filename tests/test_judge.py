import json
from unittest.mock import MagicMock, patch

from nokware.judge import Judge, keyword_overlap
from nokware.runner import JudgeBudget


def test_keyword_overlap_basic():
    assert keyword_overlap("the fee is 500 cedis", "registration fee: 500 cedis") > 0.5
    assert keyword_overlap("elephants fly south", "registration fee: 500 cedis") < 0.2


def test_no_key_uses_fallback():
    j = Judge(api_key=None, budget=JudgeBudget(limit=10))
    v = j.judge_faithfulness("the fee is 500 cedis", "registration fee: 500 cedis")
    assert v.engine == "fallback"
    assert 0.0 <= v.score <= 1.0


def test_exhausted_budget_uses_fallback():
    j = Judge(api_key="real-key-not-called", budget=JudgeBudget(limit=0))
    v = j.judge_faithfulness("a", "a")
    assert v.engine == "fallback"


def test_gemini_success_path():
    claims_payload = json.dumps({
        "claims": [
            {"claim": "the fee is 500 cedis", "supported": True},
            {"claim": "registration opens tomorrow", "supported": False},
        ]
    })
    mock_resp = MagicMock()
    mock_resp.text = claims_payload
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp

    budget = JudgeBudget(limit=10)
    with patch("google.genai.Client", return_value=mock_client):
        j = Judge(api_key="fake-key", budget=budget)
        v = j.judge_faithfulness("the fee is 500 cedis", "registration fee: 500 cedis")

    assert v.engine == "gemini"
    assert v.score == 0.5
    assert v.supported is False
    assert "registration opens tomorrow" in v.reasons
    assert budget.used == 1
