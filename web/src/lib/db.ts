import postgres from "postgres";

export type ScoreRow = {
  suite: string;
  check_id: string;
  value: number;
  passed: boolean;
  baseline: number | null;
  created_at: string;
};

export type LastRun = {
  id: string;
  started_at: string;
  status: string;
  judge_verified: boolean;
  judge_agreement: number | null;
};

// The client is created lazily, on first use, rather than at module load
// time. NEON_DATABASE_URL does not exist yet (Neon provisioning is
// pending) -- creating the client eagerly at import time would throw
// during `next build`'s module-collection pass, before any route ever
// runs. Deferring construction into each reader function means the
// module can be imported (and the production build can complete) with no
// DSN set at all; the connection is only attempted when a page actually
// renders at request time.
let client: postgres.Sql | null = null;

function getSql(): postgres.Sql {
  if (!client) {
    client = postgres(process.env.NEON_DATABASE_URL!, { ssl: "require" });
  }
  return client;
}

export async function latestScores(): Promise<ScoreRow[]> {
  const sql = getSql();
  return sql<ScoreRow[]>`
    SELECT DISTINCT ON (suite, check_id)
      suite, check_id, value, passed, baseline, created_at::text
    FROM results
    ORDER BY suite, check_id, created_at DESC`;
}

export async function lastRun(): Promise<LastRun | null> {
  const sql = getSql();
  const rows = await sql<LastRun[]>`
    SELECT id, started_at::text, status, judge_verified, judge_agreement
    FROM runs ORDER BY started_at DESC LIMIT 1`;
  return rows[0] ?? null;
}

export type CheckHistoryPoint = {
  check_id: string;
  value: number;
  created_at: string;
};

export async function checkHistory(suite: string, days = 90): Promise<CheckHistoryPoint[]> {
  const sql = getSql();
  return sql<CheckHistoryPoint[]>`
    SELECT check_id, value, created_at::text FROM results
    WHERE suite = ${suite} AND created_at >= now() - make_interval(days => ${days})
    ORDER BY created_at ASC`;
}

export type FailingTrace = {
  check_id: string;
  value: number;
  traces: Record<string, unknown>;
  created_at: string;
};

export async function failingTraces(suite: string, limit = 20): Promise<FailingTrace[]> {
  const sql = getSql();
  return sql<FailingTrace[]>`
    SELECT check_id, value, traces, created_at::text FROM results
    WHERE suite = ${suite} AND passed = false
    ORDER BY created_at DESC LIMIT ${limit}`;
}

export type Incident = {
  id: number;
  opened_at: string;
  run_id: number;
  suite: string;
  check_id: string;
  severity: string;
  state: string;
  cluster_id: number | null;
  root_cause: string | null;
  resolved_at: string | null;
};

export async function incidents(state?: string): Promise<Incident[]> {
  const sql = getSql();
  return state
    ? sql<Incident[]>`
        SELECT id, opened_at::text, run_id, suite, check_id, severity, state,
               cluster_id, root_cause, resolved_at::text
        FROM incidents WHERE state = ${state} ORDER BY opened_at DESC LIMIT 100`
    : sql<Incident[]>`
        SELECT id, opened_at::text, run_id, suite, check_id, severity, state,
               cluster_id, root_cause, resolved_at::text
        FROM incidents ORDER BY opened_at DESC LIMIT 100`;
}

export type RunRow = {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  trigger: string;
  git_sha: string;
  golden_hash: string;
  judge_verified: boolean;
  judge_agreement: number | null;
};

export async function runs(limit = 90): Promise<RunRow[]> {
  const sql = getSql();
  return sql<RunRow[]>`
    SELECT id, started_at::text, finished_at::text, status, trigger, git_sha, golden_hash,
           judge_verified, judge_agreement
    FROM runs ORDER BY started_at DESC LIMIT ${limit}`;
}

export type RunResultRow = {
  id: number;
  suite: string;
  check_id: string;
  score_type: string;
  value: number;
  passed: boolean;
  baseline: number | null;
  traces: Record<string, unknown>;
  created_at: string;
};

export async function runById(id: number): Promise<RunRow | null> {
  const sql = getSql();
  const rows = await sql<RunRow[]>`
    SELECT id, started_at::text, finished_at::text, status, trigger, git_sha, golden_hash,
           judge_verified, judge_agreement
    FROM runs WHERE id = ${id}`;
  return rows[0] ?? null;
}

export async function resultsForRun(runId: number): Promise<RunResultRow[]> {
  const sql = getSql();
  return sql<RunResultRow[]>`
    SELECT id, suite, check_id, score_type, value, passed, baseline, traces, created_at::text
    FROM results WHERE run_id = ${runId} ORDER BY suite, check_id`;
}
