from nokware.core import CheckResult
from nokware.embeddings import failure_signature


def test_failure_signature_is_stable_and_informative():
    r = CheckResult(check_id="precision_at_5", suite="africapep", score_type="statistical",
                    value=0.4, passed=False,
                    traces={"misses": [{"id": "gh-mahama-fuzzy", "query": "John Mahamma"}]})
    sig = failure_signature(r)
    assert "africapep" in sig and "precision_at_5" in sig and "John Mahamma" in sig
    assert sig == failure_signature(r)
