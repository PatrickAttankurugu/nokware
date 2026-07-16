import fs from "node:fs";
import path from "node:path";
import Link from "next/link";

// This page reads a repo file (the versioned judge prompt), not the
// database, at build time. It carries no `dynamic` export: there is nothing
// here that a static prerender can get wrong, and no NEON_DATABASE_URL
// dependency to defer past build time.
//
// The canonical prompt lives at repo root `prompts/faithfulness.txt` (what
// nokware/judge.py actually sends). web/prompts/faithfulness.txt is a
// synced copy: the Vercel CLI deploys web/ as a self-contained tree (see
// README's deploy section), so a path outside it is invisible at build
// time on Vercel even though it resolves fine in a full local checkout.
// Keep the two files identical when the prompt changes.
const faithfulnessPrompt = fs.readFileSync(
  path.join(process.cwd(), "prompts", "faithfulness.txt"),
  "utf8",
);

export const metadata = {
  title: "Methodology - Nokware",
  description: "How every Nokware score is computed, judged, and published.",
};

export default function Methodology() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <Link href="/" className="text-sm text-neutral-400 hover:underline">
        &larr; Overview
      </Link>
      <h1 className="mt-4 text-3xl font-semibold">Methodology</h1>
      <p className="mt-4 text-neutral-600 dark:text-neutral-300">
        Nokware runs three eval suites against my own production systems every night: AfricaPEP
        (PEP screening search), LexAura (regulatory RAG), and SENTINEL (agentic AML
        investigation). Every check below calls the same public API a real user would call.
        There is no privileged access path and no scoring shortcut that exists only for this
        dashboard. If a public API cannot answer a question, that is a finding, not an excluded
        case.
      </p>

      <section className="mt-10">
        <h2 className="text-xl font-medium">How each suite is scored</h2>

        <h3 className="mt-6 font-medium">AfricaPEP: search relevance</h3>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          AfricaPEP&apos;s suite is deterministic and statistical only. It never calls an LLM,
          which makes it the anchor suite: it keeps running and keeps publishing even if every
          LLM provider the other two suites depend on is down. It runs six checks: availability
          (the share of golden queries that returned a response without error); precision_at_5,
          recall_at_10, and mrr, which score ranking quality against an identity-based relevance
          set (a returned result counts as relevant only if its stable Wikidata QID matches the
          golden entry&apos;s expected identity, so two different people who happen to share a
          name are never conflated; older golden entries with no recorded QID fall back to a
          name-substring match); negative_controls, built from names that must never surface a
          PEP match, which fails on any false-positive hit or any errored negative-control query;
          and p95_latency_ms.
        </p>

        <h3 className="mt-6 font-medium">LexAura: RAG truthfulness</h3>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          LexAura&apos;s suite runs five checks and is the only suite that spends judge budget.
          availability tracks whether each golden question returned an answer at all.
          retrieval_hit_rate and citation_integrity are both deterministic: they check whether
          the known source passage and the required citation actually appear in what LexAura
          returned, with no LLM opinion involved. The suite requests full retrieval context so
          both of those checks, and faithfulness, are scored against the complete retrieved
          passage rather than the 150-character snippet the production UI truncates to; if
          LexAura ever stops returning that full context, the suite falls back to the snippet and
          records which context mode it actually got, so a silent downgrade in context quality
          shows up in the traces instead of disappearing. faithfulness is the one LLM-judged
          check: every claim in the answer is checked, claim by claim, against the retrieved
          context by a Gemini judge (the exact prompt is below), with a keyword-overlap fallback
          when the judge is unavailable, and each result records which engine produced it.
          p95_latency_ms closes out the suite.
        </p>

        <h3 className="mt-6 font-medium">SENTINEL: agent outcome integrity</h3>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          SENTINEL runs six checks against the eight seeded typology scenarios already loaded in
          its own database, triggering each investigation&apos;s real five-agent workflow and
          polling it to completion. availability tracks whether that trigger-and-poll round trip
          succeeded. typology_accuracy checks whether the expected typology appears anywhere in
          what the agents detected; typology_precision is its companion check, added so an agent
          that fires every typology on every scenario cannot score well by over-triggering.
          pipeline_completion_rate reads each agent&apos;s own error field to tell a full LLM
          completion apart from a rule-based fallback. SENTINEL runs on the same free-tier Gemini
          quota Nokware does, so some fallback completions on a given night are expected, not
          scored as a crash. sar_schema_validity checks that the resulting SAR draft carries the
          fields a downstream compliance workflow actually needs. p95_latency_ms measures the
          full trigger-to-completion round trip. One engineering detail worth stating plainly:
          because Nokware reruns the same seeded investigations every night without resetting
          them, a long-lived investigation accumulates finding rows over time. The suite keeps
          only the newest finding per agent and, past a two-minute grace window, treats anything
          older as stale leftover from a previous night&apos;s run rather than tonight&apos;s
          output, so a slow night&apos;s findings can never be mistaken for tonight&apos;s.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-medium">Drift and incidents</h2>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          A check drifts when its value moves more than 10% relative to its own 7-day rolling
          baseline. For every check except latency, drift means the value fell. For the
          p95_latency_ms checks, the comparison is inverted, since a rise, not a fall, is the
          regression there. Any drifted check opens an incident automatically, the same night it
          is detected. There is no code path that skips writing a drifted result and no manual
          review gate standing between a bad score and an open incident. The loop opens and
          annotates incidents; only a human commit changes their state afterward, moving them
          through investigating, explained, and resolved.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-medium">Judge budget and spend policy</h2>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          LLM-judge calls are capped in code, not left to a provider&apos;s own rate limit to
          catch problems first. The harness&apos;s default cap is 200 judge calls per run; the
          LexAura suite currently runs at a tighter cap of 160, leaving headroom under the free
          tier&apos;s daily quota for the meta-eval below. Once a suite&apos;s budget is
          exhausted, remaining judge checks are skipped and marked as such, never silently
          dropped. The budget counts attempts, not successes: a call that reaches the model and
          returns an unusable response has still spent budget, because the cost was already
          incurred. The one exception is a query that already failed at the retrieval step:
          LexAura does not spend judge budget re-confirming a result it already knows is a forced
          miss.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-medium">Judge meta-eval</h2>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          Before any LLM-judged score is allowed to publish, the same judge runs against a small,
          hand-labeled fixture set of answer/context pairs with a known correct verdict
          (golden/judge.jsonl). If the judge agrees with the human labels at least 85% of the
          time, that run&apos;s judge-derived scores publish as verified. Below that threshold,
          they still publish, nothing is hidden, but every LLM-judged score in that run is
          flagged unverified, and the run&apos;s judge_verified and judge_agreement fields, shown
          on the Runs page, record exactly why. This meta-eval runs whenever any suite in that
          run produced an LLM-judged score. Today that means it runs whenever LexAura runs, since
          AfricaPEP and SENTINEL never call a judge at all.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-medium">The judge prompt</h2>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          This is the exact prompt sent to the judge for every faithfulness check, unedited and
          versioned in the repo alongside the code:
        </p>
        <pre className="mt-3 overflow-x-auto rounded-md border bg-neutral-50 p-4 text-xs leading-relaxed dark:bg-neutral-900">
          {faithfulnessPrompt}
        </pre>
      </section>

      <section className="mt-10">
        <h2 className="text-xl font-medium">Honesty rules</h2>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          These are enforced by how the code is structured, not by a policy someone could forget
          to follow:
        </p>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-neutral-600 dark:text-neutral-300">
          <li>Regressions publish automatically; no hide-a-run path exists in code.</li>
          <li>Every score links to raw traces.</li>
          <li>LLM-judged scores display judge-verification status.</li>
          <li>Last 90 days shown unedited.</li>
        </ol>
      </section>

      <section className="mt-10 mb-4">
        <h2 className="text-xl font-medium">Known limitations</h2>
        <p className="mt-2 text-neutral-600 dark:text-neutral-300">
          Being honest about a monitoring system&apos;s own blind spots is part of the point. As
          of this writing:
        </p>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-neutral-600 dark:text-neutral-300">
          <li>
            AfricaPEP&apos;s golden set matches on the API&apos;s stable Wikidata QID for every
            positive entry, so precision, recall, and MRR reflect real identity rather than name
            overlap. The suite still supports a name-substring fallback for any future entry added
            without a recorded QID, but none of the current 93 positive entries use it.
          </li>
          <li>
            LexAura&apos;s golden set runs against the same production endpoint real users hit,
            sharing a daily generation quota of roughly 20 with them. The suite paces its
            requests to stay under LexAura&apos;s own rate limit, but this is a genuine ceiling on
            how large that suite&apos;s nightly run can get.
          </li>
          <li>
            SENTINEL&apos;s nightly run draws on its own free-tier LLM quota, so some share of
            each night&apos;s agent runs completing through rule-based fallback rather than the
            full LLM path is expected behavior, not a fault to chase.
          </li>
          <li>
            faithfulness scoring requires a configured GEMINI_API_KEY. Without one, every
            faithfulness check falls back to a keyword-overlap heuristic, which scores
            conservatively lower than the LLM judge and is not a substitute for it.
          </li>
          <li>
            The nightly run is scheduled for 08:30 GMT rather than midnight, deliberately:
            Gemini&apos;s free-tier daily quota resets at midnight Pacific time, and the run is
            timed to land after that reset so it starts each night with a full day&apos;s quota
            rather than whatever the previous day&apos;s traffic left behind.
          </li>
        </ul>
      </section>
    </main>
  );
}
