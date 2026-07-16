# Nokware: Public AI Reliability Ledger. Design Spec

**Date:** 2026-07-16
**Owner:** Patrick Attankurugu
**Status:** Approved design, pre-implementation
**Repo:** `Portfolio/projects/nokware` (new; MIT license)
**Live surface:** nokware.patrickaiafrica.com

## 1. What this is

Nokware (Twi: "truth") is a public, continuously updated report card for Patrick's three production AI systems: SENTINEL (agentic AML investigations), AfricaPEP (PEP screening search), and LexAura (regulatory RAG). An autonomous nightly eval loop runs versioned eval suites against the live public APIs of those systems, stores scored results with full traces, detects drift, opens incidents, and publishes everything to a public dashboard. The eval harness is open source.

**Purpose (in priority order):**
1. Make Patrick interview-fluent in evals and reliability for LLM/agent systems, with public artifacts to point at.
2. Produce a LinkedIn post (and a follow-up content lane) that generates inbound interest from hiring managers for remote AI Engineer roles.
3. Genuinely monitor his live portfolio systems, so the portfolio's "figures from live production data" claim stays continuously true.

**Audience:** hiring managers and senior engineers evaluating Patrick. The design optimizes for engineering-depth signal, not for third-party adoption.

## 2. Goals and non-goals

**Goals (v1, 2-week build):**
- Python eval harness with three scorer types: deterministic, statistical, LLM-judge (with judge meta-eval).
- Three suites, one per system, run nightly by a GitHub Actions loop.
- Neon Postgres + pgvector storage with full traces and failure clustering.
- Public Next.js dashboard: score tiles, trends, run log, incident queue, methodology page.
- MCP server: `get_scores`, `get_run_detail`, `list_incidents`, `trigger_run` (authenticated).
- LinkedIn post written from real run data after 7-10 nights of operation.

**Non-goals (v1):**
- Evaluating systems Patrick does not own.
- Generic framework adapters (LangChain/LangGraph plugin interfaces, etc.).
- Auto-remediation of any kind. The loop reports; it never modifies the systems under test.
- Anything touching Ramah data or any non-public data. Systems under test use public/synthetic data only.
- Paid infrastructure. Free tiers throughout (Neon, Vercel, GitHub Actions, Gemini free tier).

## 3. Architecture

```
GitHub Actions (nightly cron 02:00 GMT + manual dispatch)
  └─ nokware run --all
       ├─ Suite: africapep  ──HTTP──►  api-pep.patrickaiafrica.com
       ├─ Suite: lexaura    ──HTTP──►  LexAura public endpoint
       ├─ Suite: sentinel   ──HTTP──►  sentinel.patrickaiafrica.com
       ├─ Judge meta-eval (gates LLM-judged scores)
       └─ Writer ──► Neon Postgres (+pgvector)
            ├─ drift detector ──► incidents
            └─ runs/YYYY-MM-DD.md summary committed to repo

Dashboard (Next.js 16, Vercel, server components) ──reads──► Neon
MCP server (FastMCP, Python, same repo)          ──reads──► Neon
                                                  └─ trigger_run ──► GitHub workflow_dispatch
```

**Components and single responsibilities:**

| Component | Job | Stack |
|---|---|---|
| `nokware/` package | Define and score checks; produce results with traces | Python 3.12, httpx, pydantic |
| Suites (`suites/*.py` + `golden/*.jsonl`) | System-specific checks against public APIs | Python + versioned golden files |
| Loop (`.github/workflows/nightly.yml`) | Schedule, budget caps, drift detection, incident creation, run summary commit | GitHub Actions |
| Storage | Runs, results, incidents, embeddings | Neon Postgres + pgvector |
| Dashboard (`web/`) | Public read-only ledger | Next.js 16, Tailwind v4, Vercel |
| MCP server (`nokware/mcp_server.py`) | Ledger access for agents | FastMCP |

**Access rule:** suites hit the systems' public APIs exactly as a user would. No privileged backdoors. If the public API cannot answer, that is a finding.

## 4. Eval suites

### 4.1 AfricaPEP: search relevance (deterministic + statistical, no LLM)
- Golden set: ~100 queries in `golden/africapep.jsonl`. Categories: exact names, fuzzy misspellings, missing diacritics, cross-country ambiguous names, negative controls (must NOT match).
- Scores: precision@5, recall@10, MRR, p95 latency, availability.
- This suite is the anchor: runs even if all LLM providers are down.

### 4.2 LexAura: RAG truthfulness
- Golden set: ~50 regulatory questions with known source passages in `golden/lexaura.jsonl`.
- Scores per answer:
  - **Faithfulness** (LLM-judge): every claim in the answer checked claim-by-claim against retrieved context.
  - **Retrieval hit rate** (no judge): known source passage present in retrieved context, matched by pgvector similarity above threshold.
  - **Citation integrity** (deterministic): cited sections exist in the corpus.
- The retrieval/generation split is the point: distinguishes search failures from hallucination.

### 4.3 SENTINEL: agent outcome integrity
- Scenarios: the 8 seeded typologies with known ground truth (synthetic data).
- Scores: typology detection accuracy, pipeline completion rate (full LLM path vs rule fallback, which SENTINEL self-reports), structured-output validity (SAR draft schema), end-to-end latency.
- One robustness probe: one scenario per run executed with the judge-side expectation that SENTINEL may be rate-limited; the check asserts graceful degradation (complete output via fallback), not perfection.

### 4.4 Judge meta-eval (gates all LLM-judged scores)
- Fixture set: ~20 hand-labeled answer/context pairs with known verdicts in `golden/judge.jsonl`.
- Before LLM-judged scores publish, the judge must agree with human labels at >= 85%. Below that, the run publishes those scores flagged **unverified**.
- Judge: Gemini (existing key) with deterministic fallback heuristics; all judge prompts versioned in repo and linked from the methodology page.

**Golden sets are files in the repo** (auditable, versioned). The DB stores only the golden-set git hash used by each run.

## 5. Data model (Neon Postgres)

- `runs(id, started_at, finished_at, git_sha, golden_hash, trigger, status, judge_verified bool, judge_agreement float)`
- `results(id, run_id, suite, check_id, score_type, value float, passed bool, baseline float, traces jsonb, embedding vector(768))`
- `incidents(id, opened_at, run_id, suite, check_id, severity, state enum(investigating, explained, resolved), cluster_id, root_cause text, resolved_at)`

pgvector jobs: (1) cluster failing-result embeddings so recurring failure modes group across runs; (2) semantic similarity scoring for retrieval hit rate.

## 6. Loop engineering rules

- Nightly cron 02:00 GMT + `workflow_dispatch` for manual/MCP-triggered runs.
- **Budget caps in code:** max LLM-judge calls per run (default 200); exceeded = remaining LLM checks skipped and marked, never silently dropped.
- **Read-only guarantee:** the loop holds no write credentials to any system under test.
- **No self-modification:** thresholds and golden sets change only by human commit.
- Drift rule: score below 7-day rolling baseline by more than 10% relative (per-check overridable) opens an incident.
- Each run commits `runs/YYYY-MM-DD.md` (compact summary) to the repo; the Actions history itself is public.
- Incident lifecycle: loop opens and annotates; only a human commit closes (states: investigating → explained → resolved).

## 7. Dashboard (public)

Pages:
1. **Overview:** per-system score tiles (current vs 7-day), status strip, last-run time.
2. **System detail:** trend charts per check, recent failures with traces, failure clusters.
3. **Incidents:** public triage queue with states and written root causes.
4. **Runs:** run log linking to raw results.
5. **Methodology:** how every score is computed, judge prompts, meta-eval results, known limitations, honesty rules. This page is the hiring-manager magnet and gets writing-quality attention.

**Honesty rules (enforced by design, stated on methodology page):**
1. Regressions publish automatically; no hide-a-run path exists in code.
2. Every score links to raw traces.
3. LLM-judged scores display judge-verification status.
4. Last 90 days shown unedited.

## 8. MCP server

Tools: `get_scores(system?, since?)`, `get_run_detail(run_id)`, `list_incidents(state?)`, `trigger_run(suite?)` (requires token; fires GitHub workflow_dispatch). Read tools are public-data only, safe by construction. Server ships in the repo with setup docs; usable from Claude Code/Desktop.

## 9. Testing

- Unit tests per scorer with known-answer fixtures.
- Judge meta-eval doubles as the judge regression suite.
- One integration test per suite against recorded API responses (CI never hits live systems).
- CI (GitHub Actions) on every PR: lint, types, tests.
- The harness being visibly well-tested is part of the portfolio signal.

## 10. Secrets and config

`NEON_DATABASE_URL`, `GEMINI_API_KEY`, `AFRICAPEP_API_KEY`, `SENTINEL_BASE_URL`, `LEXAURA_BASE_URL`, `GH_DISPATCH_TOKEN` (MCP trigger only). All via GitHub Actions secrets and Vercel env. Nothing committed; `.env.example` with placeholders only.

## 11. Build plan (2 weeks, sharp)

**Week 1:** harness core (Suite/Check/Score, scorers, traces) → Neon schema → AfricaPEP suite + golden set → nightly workflow running end-to-end with real scores → drift detector + incidents.
**Week 2:** LexAura suite + judge + meta-eval → SENTINEL suite → dashboard (all 5 pages) → MCP server → methodology page polish → DNS + deploy.
**Then:** 7-10 quiet nights of real runs → LinkedIn post written from actual data (via brand-copy-reviewer; no emojis; claims must match the live dashboard).

**Success criteria:** 7 consecutive green nightly runs; dashboard live on the subdomain; at least one real incident opened and root-caused; post drafted from real data.

## 12. Risks

| Risk | Mitigation |
|---|---|
| LexAura/SENTINEL APIs too unstable to eval | That instability IS content; incidents and root causes are the story |
| Gemini free-tier limits mid-run | Budget caps + skip-and-mark, deterministic anchor suite always completes |
| 2 weeks slips | AfricaPEP suite + dashboard alone is already shippable; cut SENTINEL robustness probe first, then MCP `trigger_run` |
| Public bad scores look bad | Honesty rules reframe: a triaged incident with a written root cause is senior-engineer signal |
