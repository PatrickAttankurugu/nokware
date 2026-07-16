import sys

import nokware.drift
import nokware.runner
from nokware.core import Check, CheckResult, Suite
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


class _FakeLedger:
    """Stands in for nokware.db.Ledger: start/write succeed, finish_run raises
    (same DB outage as the post-write step that already crashed)."""

    def __init__(self, dsn):
        pass

    def start_run(self, git_sha, golden_hash, trigger):
        return 1

    def write_results(self, run_id, results):
        return {}

    def finish_run(self, run_id, status, judge_verified, judge_agreement):
        raise RuntimeError("db still down")


def _fake_check() -> CheckResult:
    return CheckResult(check_id="c1", suite="fake", score_type="deterministic",
                       value=1.0, passed=True, traces={})


def test_finish_run_failure_is_exception_safe(monkeypatch, capsys):
    """The except block that marks a run 'failed' must not itself crash: the
    original error is always reported first, a finish_run failure is reported
    separately, and main() still returns 2 instead of raising."""
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(nokware.runner, "Ledger", _FakeLedger)
    monkeypatch.setattr(
        nokware.runner, "SUITE_BUILDERS",
        {"fake": lambda: Suite(name="fake", checks=[Check(id="c1", suite="fake",
                                                           description="", fn=_fake_check)])},
    )

    def _boom(value, baseline, higher_is_worse=False):
        raise RuntimeError("drift check exploded")

    monkeypatch.setattr(nokware.drift, "is_drift", _boom)
    monkeypatch.setattr(sys, "argv", ["nokware", "run", "--suite", "fake"])

    rc = nokware.runner.main()

    assert rc == 2
    err = capsys.readouterr().err
    assert "run 1 failed after persisting results" in err
    assert "RuntimeError: drift check exploded" in err
    assert "additionally failed to mark run as failed" in err
    assert "db still down" in err
    # original error must be printed before the finish_run failure note
    assert err.index("run 1 failed after persisting results") < \
        err.index("additionally failed to mark run as failed")
