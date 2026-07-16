import { latestScores, lastRun } from "@/lib/db";
import { ScoreTile } from "@/components/score-tile";

// TODO: switch back to `export const revalidate = 300` once NEON_DATABASE_URL
// is provisioned. Until then, `revalidate` alone would let Next.js attempt a
// static prerender of this page at build time (there is no database yet to
// query), which fails the production build. `force-dynamic` skips prerender
// entirely and defers the query to request time.
export const dynamic = "force-dynamic";

const SYSTEMS: Record<string, { title: string; blurb: string }> = {
  africapep: { title: "AfricaPEP", blurb: "PEP screening search relevance" },
  lexaura: { title: "LexAura", blurb: "Regulatory RAG truthfulness" },
  sentinel: { title: "SENTINEL", blurb: "Agentic AML investigation integrity" },
};

export default async function Overview() {
  const [scores, run] = await Promise.all([latestScores(), lastRun()]);
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <h1 className="text-3xl font-semibold">Nokware</h1>
      <p className="mt-2 text-neutral-500">
        A public reliability ledger for my production AI systems. Nokware is Twi for truth:
        these scores publish nightly, regressions included.
      </p>
      {run && (
        <p className="mt-1 text-sm text-neutral-400">
          Last run {run.started_at} ({run.status}
          {run.judge_agreement != null && `, judge agreement ${run.judge_agreement}`})
        </p>
      )}
      <div className="mt-10 grid gap-6 md:grid-cols-3">
        {Object.entries(SYSTEMS).map(([slug, meta]) => (
          <ScoreTile
            key={slug}
            slug={slug}
            title={meta.title}
            blurb={meta.blurb}
            rows={scores.filter((s) => s.suite === slug)}
          />
        ))}
      </div>
    </main>
  );
}
