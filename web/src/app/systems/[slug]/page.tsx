import Link from "next/link";
import { notFound } from "next/navigation";
import { checkHistory, failingTraces, lastRun, latestScores } from "@/lib/db";
import { Trend } from "@/components/trend";

// TODO: switch back to `export const revalidate = 300` once NEON_DATABASE_URL
// is provisioned. See web/src/app/page.tsx for the full explanation -- until
// then, force-dynamic keeps this route from attempting a static prerender
// (and a doomed query) at build time.
export const dynamic = "force-dynamic";

const SYSTEMS: Record<string, { title: string; blurb: string }> = {
  africapep: { title: "AfricaPEP", blurb: "PEP screening search relevance" },
  lexaura: { title: "LexAura", blurb: "Regulatory RAG truthfulness" },
  sentinel: { title: "SENTINEL", blurb: "Agentic AML investigation integrity" },
};

// Checks currently scored by the LLM judge (score_type "llm_judge" in
// suites/lexaura.py). latestScores() does not select score_type, so this is
// hardcoded to today's suites rather than read from a row -- if a suite adds
// or removes a judge-scored check, update this list (or better, have
// latestScores() return score_type and read it from there instead).
const JUDGE_CHECKS: Record<string, Set<string>> = {
  lexaura: new Set(["faithfulness"]),
};

// Checks where a higher value is worse -- mirrors nokware/runner.py's
// LATENCY_CHECKS, which the drift detector uses to invert its comparison.
const HIGHER_IS_WORSE_CHECKS = new Set(["p95_latency_ms"]);

function unitFor(checkId: string): string {
  return HIGHER_IS_WORSE_CHECKS.has(checkId) ? "ms" : "";
}

export default async function SystemDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const meta = SYSTEMS[slug];
  if (!meta) notFound();

  const [history, failing, latest, run] = await Promise.all([
    checkHistory(slug, 90),
    failingTraces(slug, 20),
    latestScores(),
    lastRun(),
  ]);

  const suiteLatest = latest.filter((r) => r.suite === slug);

  const pointsByCheck = new Map<string, { value: number; created_at: string }[]>();
  for (const row of history) {
    const arr = pointsByCheck.get(row.check_id) ?? [];
    arr.push({ value: row.value, created_at: row.created_at });
    pointsByCheck.set(row.check_id, arr);
  }

  const judgeChecks = JUDGE_CHECKS[slug];
  const hasJudgeChecks = suiteLatest.some((r) => judgeChecks?.has(r.check_id));

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        &larr; Overview
      </Link>
      <h1 className="mt-4 text-3xl font-semibold">{meta.title}</h1>
      <p className="mt-2 text-neutral-500">{meta.blurb}</p>

      {hasJudgeChecks && run && (
        <p className="mt-3 rounded-md border border-neutral-200 px-3 py-2 text-sm text-neutral-500 dark:border-neutral-800">
          This system has LLM-judged checks. In the most recent run, judge scores were{" "}
          {run.judge_verified ? "verified" : "flagged unverified"} against the meta-eval fixture
          set
          {run.judge_agreement != null &&
            ` (${Math.round(run.judge_agreement * 100)}% agreement)`}
          . See the{" "}
          <Link href="/methodology" className="underline">
            methodology page
          </Link>{" "}
          for how this gate works.
        </p>
      )}

      <section className="mt-10">
        <h2 className="text-lg font-medium">Checks, last 90 days</h2>
        {suiteLatest.length === 0 ? (
          <p className="mt-2 text-sm text-neutral-400">no results yet</p>
        ) : (
          <div className="mt-4 grid gap-6 sm:grid-cols-2">
            {suiteLatest.map((row) => {
              const isJudged = judgeChecks?.has(row.check_id) ?? false;
              return (
                <div key={row.check_id} className="rounded-lg border p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm">{row.check_id}</span>
                    {isJudged && (
                      <span className="rounded-full border border-neutral-300 px-2 py-0.5 text-[11px] text-neutral-500 dark:border-neutral-700">
                        judge {run?.judge_verified ? "verified" : "unverified"}
                      </span>
                    )}
                  </div>
                  <p
                    className={`mt-1 text-sm ${row.passed ? "text-emerald-600" : "text-red-600"}`}
                  >
                    {row.value}
                    {unitFor(row.check_id)} {row.passed ? "pass" : "fail"}
                  </p>
                  <div className="mt-3 overflow-x-auto">
                    <Trend
                      points={pointsByCheck.get(row.check_id) ?? []}
                      baseline={row.baseline}
                      higherIsWorse={HIGHER_IS_WORSE_CHECKS.has(row.check_id)}
                      unit={unitFor(row.check_id)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="mt-12">
        <h2 className="text-lg font-medium">Recent failures</h2>
        {failing.length === 0 ? (
          <p className="mt-2 text-sm text-neutral-400">
            no failing checks in the recorded history
          </p>
        ) : (
          <div className="mt-4 space-y-2">
            {failing.map((f, i) => (
              <details key={i} className="rounded-md border p-3">
                <summary className="cursor-pointer text-sm">
                  <span className="font-mono">{f.check_id}</span> &middot; {f.value}
                  {unitFor(f.check_id)} &middot; {f.created_at}
                </summary>
                <pre className="mt-2 overflow-x-auto rounded bg-neutral-50 p-3 text-xs dark:bg-neutral-900">
                  {JSON.stringify(f.traces, null, 2)}
                </pre>
              </details>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
