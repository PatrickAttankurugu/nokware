from nokware.core import CheckResult
from nokware.runner import JudgeBudget, write_summary


def test_budget_exhausts():
    b = JudgeBudget(limit=2)
    assert b.take() and b.take()
    assert not b.take()


def test_write_summary(tmp_path):
    out = tmp_path / "2026-07-20.md"
    write_summary([CheckResult(check_id="mrr", suite="africapep", score_type="statistical",
                               value=0.91, passed=True, traces={})], str(out))
    text = out.read_text()
    assert "africapep" in text and "0.91" in text and "PASS" in text
