import Link from "next/link";
import { runs } from "@/lib/db";

// TODO: same reasoning as web/src/app/page.tsx -- force-dynamic until
// NEON_DATABASE_URL is provisioned, so the build never attempts to query at
// prerender time.
export const dynamic = "force-dynamic";

const ACTIONS_URL = "https://github.com/PatrickAttankurugu/nokware/actions";

export default async function Runs() {
  const rows = await runs(90);

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        &larr; Overview
      </Link>
      <h1 className="mt-4 text-3xl font-semibold">Runs</h1>
      <p className="mt-2 text-neutral-500">
        The run log. Each row is one nightly or manually dispatched run, linking to its GitHub
        Actions history.
      </p>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b text-left text-neutral-400">
              <th className="py-2 pr-4 font-normal">Started</th>
              <th className="py-2 pr-4 font-normal">Status</th>
              <th className="py-2 pr-4 font-normal">Trigger</th>
              <th className="py-2 pr-4 font-normal">Commit</th>
              <th className="py-2 pr-4 font-normal">Golden set</th>
              <th className="py-2 font-normal">Judge</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-6 text-neutral-400">
                  no runs recorded yet
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-b align-top last:border-0">
                  <td className="py-2 pr-4 tabular-nums text-neutral-500">
                    <Link href={`/runs/${r.id}`} className="underline">
                      {r.started_at}
                    </Link>
                  </td>
                  <td
                    className={`py-2 pr-4 ${
                      r.status === "completed" ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {r.status}
                  </td>
                  <td className="py-2 pr-4">{r.trigger}</td>
                  <td className="py-2 pr-4">
                    <a
                      href={ACTIONS_URL}
                      target="_blank"
                      rel="noreferrer"
                      className="font-mono underline"
                    >
                      {r.git_sha}
                    </a>
                  </td>
                  <td className="py-2 pr-4 font-mono text-neutral-500">{r.golden_hash}</td>
                  <td className="py-2">
                    {r.judge_agreement != null ? (
                      <span className={r.judge_verified ? "text-emerald-600" : "text-red-600"}>
                        {r.judge_verified ? "verified" : "unverified"} (
                        {Math.round(r.judge_agreement * 100)}%)
                      </span>
                    ) : (
                      <span className="text-neutral-400">n/a</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-8 text-sm">
        <a href={ACTIONS_URL} target="_blank" rel="noreferrer" className="underline">
          View all workflow runs on GitHub Actions
        </a>
      </p>
    </main>
  );
}
