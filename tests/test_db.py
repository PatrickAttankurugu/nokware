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
    baselines = ledger.write_results(run_id, [CheckResult(
        check_id=check_id, suite=suite, score_type="statistical",
        value=0.9, passed=True, traces={"n": 100},
    )])
    assert baselines == {(suite, check_id): None}  # no prior rows yet, so no baseline
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


def test_set_result_embedding_roundtrip():
    ledger = make_ledger()
    suite = f"testsuite_{uuid4().hex[:8]}"
    run_id = ledger.start_run(git_sha="abc123", golden_hash="g1", trigger="test")
    ledger.write_results(run_id, [CheckResult(
        check_id="faithfulness", suite=suite, score_type="llm_judge",
        value=0.4, passed=False, traces={},
    )])
    with ledger._conn() as conn:
        result_id = conn.execute(
            "SELECT id FROM results WHERE run_id = %s AND suite = %s", (run_id, suite),
        ).fetchone()[0]

    embedding = [1.0] + [0.0] * 767
    ledger.set_result_embedding(result_id, embedding)

    with ledger._conn() as conn:
        row = conn.execute(
            "SELECT embedding IS NOT NULL FROM results WHERE id = %s", (result_id,),
        ).fetchone()
    assert row[0] is True


def test_assign_cluster_groups_similar_embeddings():
    from nokware.embeddings import assign_cluster

    ledger = make_ledger()
    suite = f"testsuite_{uuid4().hex[:8]}"
    run_id = ledger.start_run(git_sha="abc123", golden_hash="g1", trigger="test")

    def make_failed_result(check_id: str) -> int:
        ledger.write_results(run_id, [CheckResult(
            check_id=check_id, suite=suite, score_type="llm_judge",
            value=0.0, passed=False, traces={},
        )])
        with ledger._conn() as conn:
            return conn.execute(
                "SELECT id FROM results WHERE run_id = %s AND suite = %s AND check_id = %s",
                (run_id, suite, check_id),
            ).fetchone()[0]

    # Hand-built, normalized 768-dim vectors. vec_a and vec_b point in nearly
    # the same direction (cosine similarity well above the 0.85 threshold);
    # vec_c is orthogonal to both (similarity ~0, well below threshold).
    # NOTE: assign_cluster's nearest-neighbor query is not scoped to a single
    # suite (a known limitation, tracked in the v1 backlog), so in a
    # long-lived shared test database these assertions assume no unrelated
    # leftover embedding happens to sit closer to these vectors than the ones
    # this test creates.
    vec_a = [1.0, 0.0] + [0.0] * 766
    vec_b_raw = [0.99, 0.14] + [0.0] * 766
    norm_b = sum(x * x for x in vec_b_raw) ** 0.5
    vec_b = [x / norm_b for x in vec_b_raw]
    vec_c = [0.0, 1.0] + [0.0] * 766

    id_a = make_failed_result("check_a")
    id_b = make_failed_result("check_b")
    id_c = make_failed_result("check_c")

    ledger.set_result_embedding(id_a, vec_a)
    cluster_a = assign_cluster(ledger, id_a, vec_a)
    assert cluster_a == id_a  # nothing else embedded yet -> seeds its own cluster

    ledger.set_result_embedding(id_b, vec_b)
    cluster_b = assign_cluster(ledger, id_b, vec_b)
    assert cluster_b == id_a  # similar enough to vec_a -> joins its cluster

    ledger.set_result_embedding(id_c, vec_c)
    cluster_c = assign_cluster(ledger, id_c, vec_c)
    assert cluster_c == id_c  # orthogonal to a/b -> gets its own cluster


def test_has_open_incident():
    ledger = make_ledger()
    suite = f"testsuite_{uuid4().hex[:8]}"
    check_id = "precision_at_5"
    run_id = ledger.start_run(git_sha="abc123", golden_hash="g1", trigger="test")

    assert ledger.has_open_incident(suite, check_id) is False

    inc_id = ledger.open_incident(run_id, suite, check_id,
                                  severity="regression", root_cause_hint="drop vs baseline")
    assert ledger.has_open_incident(suite, check_id) is True

    with ledger._conn() as conn:
        conn.execute("UPDATE incidents SET state = 'resolved', resolved_at = now() WHERE id = %s",
                     (inc_id,))
    assert ledger.has_open_incident(suite, check_id) is False
