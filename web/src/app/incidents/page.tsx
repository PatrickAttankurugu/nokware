import Link from "next/link";
import { incidents } from "@/lib/db";

// TODO: no revalidate window is set here (or on any DB-reading route) until
// NEON_DATABASE_URL is provisioned -- see web/src/app/page.tsx for the full
// explanation. force-dynamic keeps this route from attempting a doomed
// static prerender at build time.
export const dynamic = "force-dynamic";

const STATES = ["investigating", "explained", "resolved"] as const;

const STATE_STYLES: Record<string, string> = {
  investigating: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  explained: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  resolved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
};

export default async function Incidents({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  const { state } = await searchParams;
  const filterState = state && (STATES as readonly string[]).includes(state) ? state : undefined;
  const rows = await incidents(filterState);

  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        &larr; Overview
      </Link>
      <h1 className="mt-4 text-3xl font-semibold">Incidents</h1>
      <p className="mt-2 text-neutral-500">
        A public triage queue. Every regression the nightly loop detects opens an entry here.
      </p>

      <div className="mt-6 flex flex-wrap gap-2 text-sm">
        <Link
          href="/incidents"
          className={`rounded-full border px-3 py-1 ${
            !filterState
              ? "border-neutral-900 dark:border-neutral-100"
              : "border-neutral-300 text-neutral-500 dark:border-neutral-700"
          }`}
        >
          all
        </Link>
        {STATES.map((s) => (
          <Link
            key={s}
            href={`/incidents?state=${s}`}
            className={`rounded-full border px-3 py-1 ${
              filterState === s
                ? "border-neutral-900 dark:border-neutral-100"
                : "border-neutral-300 text-neutral-500 dark:border-neutral-700"
            }`}
          >
            {s}
          </Link>
        ))}
      </div>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b text-left text-neutral-400">
              <th className="py-2 pr-4 font-normal">Opened</th>
              <th className="py-2 pr-4 font-normal">Suite / check</th>
              <th className="py-2 pr-4 font-normal">Severity</th>
              <th className="py-2 pr-4 font-normal">State</th>
              <th className="py-2 font-normal">Root cause</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-6 text-neutral-400">
                  no incidents{filterState ? ` in state "${filterState}"` : ""} yet
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-b align-top last:border-0">
                  <td className="py-2 pr-4 tabular-nums text-neutral-500">{r.opened_at}</td>
                  <td className="py-2 pr-4 font-mono">
                    {r.suite}/{r.check_id}
                  </td>
                  <td className="py-2 pr-4">{r.severity}</td>
                  <td className="py-2 pr-4">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${STATE_STYLES[r.state] ?? ""}`}
                    >
                      {r.state}
                    </span>
                  </td>
                  <td className="py-2 text-neutral-600 dark:text-neutral-300">
                    {r.root_cause ?? "not yet written"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-8 text-sm text-neutral-400">
        Incidents are opened automatically by the nightly loop. Only a human commit can close
        one.
      </p>
    </main>
  );
}
