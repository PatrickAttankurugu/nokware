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
