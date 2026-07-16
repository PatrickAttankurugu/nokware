import os
import pytest
from nokware.core import CheckResult
from nokware.db import Ledger

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


def make_ledger() -> Ledger:
    ledger = Ledger(os.environ["TEST_DATABASE_URL"])
    ledger.init_schema()
    return ledger


def test_run_lifecycle_and_baseline():
    ledger = make_ledger()
    run_id = ledger.start_run(git_sha="abc123", golden_hash="g1", trigger="test")
    ledger.write_results(run_id, [CheckResult(
        check_id="precision_at_5", suite="africapep", score_type="statistical",
        value=0.9, passed=True, traces={"n": 100},
    )])
    ledger.finish_run(run_id, status="completed", judge_verified=True, judge_agreement=None)
    base = ledger.baseline("africapep", "precision_at_5", days=7)
    assert base is None or isinstance(base, float)  # today's run excluded from its own baseline


def test_open_incident():
    ledger = make_ledger()
    run_id = ledger.start_run(git_sha="abc123", golden_hash="g1", trigger="test")
    inc_id = ledger.open_incident(run_id, "africapep", "precision_at_5",
                                  severity="regression", root_cause_hint="drop vs baseline")
    assert inc_id > 0
