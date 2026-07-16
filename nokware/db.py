import json

import psycopg

from nokware.core import CheckResult

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS runs (
  id BIGSERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  git_sha TEXT NOT NULL,
  golden_hash TEXT NOT NULL,
  trigger TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  judge_verified BOOLEAN NOT NULL DEFAULT true,
  judge_agreement REAL
);

CREATE TABLE IF NOT EXISTS results (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES runs(id),
  suite TEXT NOT NULL,
  check_id TEXT NOT NULL,
  score_type TEXT NOT NULL,
  value REAL NOT NULL,
  passed BOOLEAN NOT NULL,
  baseline REAL,
  traces JSONB NOT NULL DEFAULT '{}',
  embedding vector(768),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_results_suite_check ON results (suite, check_id, created_at);

CREATE TABLE IF NOT EXISTS incidents (
  id BIGSERIAL PRIMARY KEY,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  run_id BIGINT NOT NULL REFERENCES runs(id),
  suite TEXT NOT NULL,
  check_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'investigating',
  cluster_id INT,
  root_cause TEXT,
  resolved_at TIMESTAMPTZ
);
"""


class Ledger:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _conn(self):
        return psycopg.connect(self.dsn)

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(SCHEMA_SQL)

    def start_run(self, git_sha: str, golden_hash: str, trigger: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "INSERT INTO runs (git_sha, golden_hash, trigger) VALUES (%s,%s,%s) RETURNING id",
                (git_sha, golden_hash, trigger),
            ).fetchone()
            return row[0]

    def write_results(self, run_id: int, results: list[CheckResult]) -> None:
        with self._conn() as conn:
            for r in results:
                baseline = self._baseline_on(conn, r.suite, r.check_id)
                conn.execute(
                    """INSERT INTO results (run_id, suite, check_id, score_type, value, passed, baseline, traces)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, r.suite, r.check_id, r.score_type, r.value, r.passed,
                     baseline, json.dumps(r.traces)),
                )

    def finish_run(self, run_id: int, status: str, judge_verified: bool,
                   judge_agreement: float | None) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE runs SET finished_at = now(), status = %s,
                   judge_verified = %s, judge_agreement = %s WHERE id = %s""",
                (status, judge_verified, judge_agreement, run_id),
            )

    def _baseline_on(self, conn, suite: str, check_id: str, days: int = 7) -> float | None:
        row = conn.execute(
            """SELECT AVG(value) FROM results
               WHERE suite = %s AND check_id = %s
                 AND created_at >= now() - make_interval(days => %s)
                 AND created_at < date_trunc('day', now())""",
            (suite, check_id, days),
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def baseline(self, suite: str, check_id: str, days: int = 7) -> float | None:
        with self._conn() as conn:
            return self._baseline_on(conn, suite, check_id, days)

    def open_incident(self, run_id: int, suite: str, check_id: str,
                      severity: str, root_cause_hint: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                """INSERT INTO incidents (run_id, suite, check_id, severity, root_cause)
                   VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                (run_id, suite, check_id, severity, root_cause_hint),
            ).fetchone()
            return row[0]

    def set_result_embedding(self, result_id: int, embedding: list[float]) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE results SET embedding = %s::vector WHERE id = %s",
                         (json.dumps(embedding), result_id))
