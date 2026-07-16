import os
from uuid import uuid4

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
    suite = f"testsuite_{uuid4().hex[:8]}"
    check_id = "precision_at_5"
    ledger = make_ledger()
    run_id = ledger.start_run(git_sha="abc123", golden_hash="g1", trigger="test")
    ledger.write_results(run_id, [CheckResult(
        check_id=check_id, suite=suite, score_type="statistical",
        value=0.9, passed=True, traces={"n": 100},
    )])
    ledger.finish_run(run_id, status="completed", judge_verified=True, judge_agreement=None)

    # Insert yesterday's result directly so we can prove today's row is excluded.
    with ledger._conn() as conn:
        conn.execute(
            """INSERT INTO results (run_id, suite, check_id, score_type, value, passed, traces, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s, now() - interval '1 day')""",
            (run_id, suite, check_id, "statistical", 0.5, True, "{}"),
        )

    base = ledger.baseline(suite, check_id, days=7)
    assert base == 0.5  # yesterday's row counts; today's 0.9 must not pull the mean up


def test_open_incident():
    ledger = make_ledger()
    run_id = ledger.start_run(git_sha="abc123", golden_hash="g1", trigger="test")
    inc_id = ledger.open_incident(run_id, "africapep", "precision_at_5",
                                  severity="regression", root_cause_hint="drop vs baseline")
    assert inc_id > 0
