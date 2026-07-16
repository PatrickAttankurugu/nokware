import Link from "next/link";
import { notFound } from "next/navigation";
import { resultsForRun, runById } from "@/lib/db";

// TODO: same reasoning as web/src/app/page.tsx -- force-dynamic until
// NEON_DATABASE_URL is provisioned, so the build never attempts to query at
// prerender time.
export const dynamic = "force-dynamic";

const ID_PATTERN = /^\d+$/;

export default async function RunDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!ID_PATTERN.test(id)) notFound();

  const runId = Number(id);
  const [run, results] = await Promise.all([runById(runId), resultsForRun(runId)]);
  if (!run) notFound();

  const bySuite = new Map<string, typeof results>();
  for (const r of results) {
    const arr = bySuite.get(r.suite) ?? [];
    arr.push(r);
    bySuite.set(r.suite, arr);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <Link href="/runs" className="text-sm text-neutral-400 hover:underline">
        &larr; Runs
      </Link>
      <h1 className="mt-4 text-3xl font-semibold">Run #{run.id}</h1>
      <p className="mt-2 text-neutral-500">
        Started {run.started_at}
        {run.finished_at && ` · finished ${run.finished_at}`} &middot; triggered by{" "}
        {run.trigger}
      </p>
      <p className="mt-1 text-sm">
        <span className={run.status === "completed" ? "text-emerald-600" : "text-red-600"}>
          {run.status}
        </span>{" "}
        &middot; commit <span className="font-mono">{run.git_sha}</span> &middot; golden set{" "}
        <span className="font-mono">{run.golden_hash}</span>
        {run.judge_agreement != null && (
          <>
            {" "}
            &middot;{" "}
            <span className={run.judge_verified ? "text-emerald-600" : "text-red-600"}>
              judge {run.judge_verified ? "verified" : "unverified"} (
              {Math.round(run.judge_agreement * 100)}%)
            </span>
          </>
        )}
      </p>

      {[...bySuite.entries()].map(([suite, rows]) => (
        <section key={suite} className="mt-10">
          <h2 className="text-lg font-medium">
            <Link href={`/systems/${suite}`} className="underline">
              {suite}
            </Link>
          </h2>
          <div className="mt-4 space-y-2">
            {rows.map((r) => (
              <details key={r.id} className="rounded-md border p-3">
                <summary className="cursor-pointer text-sm">
                  <span className="font-mono">{r.check_id}</span> &middot; {r.value}{" "}
                  <span className={r.passed ? "text-emerald-600" : "text-red-600"}>
                    {r.passed ? "pass" : "fail"}
                  </span>
                  {r.baseline != null && (
                    <span className="text-neutral-400"> &middot; baseline {r.baseline}</span>
                  )}
                </summary>
                <pre className="mt-2 overflow-x-auto rounded bg-neutral-50 p-3 text-xs dark:bg-neutral-900">
                  {JSON.stringify(r.traces, null, 2)}
                </pre>
              </details>
            ))}
          </div>
        </section>
      ))}

      {results.length === 0 && (
        <p className="mt-10 text-sm text-neutral-400">no results recorded for this run</p>
      )}
    </main>
  );
}
