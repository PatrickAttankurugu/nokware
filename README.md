# Nokware

Nokware (Twi for "truth") is a public, continuously updated reliability ledger for three of
Patrick Attankurugu's production AI systems: AfricaPEP (PEP screening search), LexAura
(regulatory RAG), and SENTINEL (agentic AML investigation). A nightly eval loop runs versioned
eval suites against each system's live public API, scores the results with full traces, detects
drift, opens incidents, and publishes all of it. There is no privileged access path: every check
calls the same public endpoint a real user would call, and if that endpoint cannot answer, that
is a finding, not an excluded case.

**Live dashboard:** https://nokware.vercel.app (temporary Vercel URL; see
[Custom domain](#custom-domain) below for the pending move to `nokware.patrickaiafrica.com`)

## Current status

- All three eval suites (AfricaPEP, LexAura, SENTINEL) are implemented, tested, and run
  successfully against their live systems.
- The nightly GitHub Actions loop (`.github/workflows/nightly.yml`) is registered and running on
  schedule, but currently in **dry-run mode**: `NEON_DATABASE_URL` is not provisioned yet, so
  runs print results to the workflow log and do not persist to a database. The dashboard's data
  pages (`/`, `/runs`, `/incidents`, `/systems/[slug]`) reflect this honestly, rendering a
  "database not configured yet" message rather than crashing. The methodology page is fully
  static and needs no database.
- Once the `NEON_DATABASE_URL` secret is set, the loop switches to its persisted path
  automatically (the code already branches on whether the secret is non-empty): every run of the
  workflow first calls `nokware init-db`, which applies the schema with `CREATE TABLE IF NOT
  EXISTS` / `CREATE INDEX IF NOT EXISTS` statements, so it is safe to run on every nightly
  invocation (idempotent, not a one-time migration someone has to remember to run by hand) before
  `nokware run --all` persists results. The dashboard starts showing real scores and trends, and
  drift detection and incidents go live. First real incidents are expected within the first week
  of persisted runs.
- The workflow's exit-code handling only tolerates a suite run that completed with findings
  (exit code 1): anything higher (a persistence failure, a bad `--suite` argument, etc.) fails
  the job instead of being swallowed, so a broken go-live path shows up as a red workflow run
  instead of a silent no-op.
- The AfricaPEP golden set matches on identity (stable Wikidata QID), not name substring, closing
  a false-positive gap where two different people sharing a name would both count as relevant.
- CI is green on every push (`pytest -v`, no live network calls).

## Architecture

```
GitHub Actions (nightly cron 08:30 GMT + manual dispatch)
  └─ nokware run --all
       ├─ Suite: africapep  ──HTTP──►  api-pep.patrickaiafrica.com
       ├─ Suite: lexaura    ──HTTP──►  lexaura.ramahupliftment.org
       ├─ Suite: sentinel   ──HTTP──►  sentinel.patrickaiafrica.com
       ├─ Judge meta-eval (gates LLM-judged scores)
       └─ Writer ──► Neon Postgres (+pgvector)      [pending provisioning]
            ├─ drift detector ──► incidents
            └─ runs/YYYY-MM-DD.md summary committed to repo

Dashboard (Next.js 16, Vercel, server components) ──reads──► Neon
MCP server (FastMCP, Python, same repo)          ──reads──► Neon
                                                  └─ trigger_run ──► GitHub workflow_dispatch
```

| Component | Job | Stack |
|---|---|---|
| `nokware/` | Define and score checks; produce results with traces | Python 3.12, httpx, pydantic |
| `suites/*.py` + `golden/*.jsonl` | System-specific checks against public APIs | Python + versioned golden files |
| `.github/workflows/nightly.yml` | Schedule, budget caps, drift detection, incident creation, run summary commit | GitHub Actions |
| Storage | Runs, results, incidents, embeddings | Neon Postgres + pgvector |
| `web/` | Public read-only dashboard | Next.js 16, Tailwind v4, Vercel |
| `nokware/mcp_server.py` | Ledger access for agents | FastMCP |

## The three suites

### AfricaPEP: search relevance (deterministic + statistical, no LLM)

The anchor suite: it never calls an LLM, so it keeps running and publishing even if every LLM
provider the other two suites depend on is down. Golden set: `golden/africapep.jsonl`, 108
entries (93 positive, 15 negative) across 39 countries, pulled live from the AfricaPEP API,
heads of state and finance ministers plus token-reorder and partial-name variants. Relevance is
identity-based: a result counts as relevant only if its returned Wikidata QID matches the golden
entry's expected identity.

Checks: `availability`, `precision_at_5`, `recall_at_10`, `mrr`, `negative_controls`,
`p95_latency_ms`.

### LexAura: RAG truthfulness

Golden set: `golden/lexaura.jsonl`, 8 hand-picked regulatory questions with known source
passages, verified against the live API. Kept intentionally small: the deployed LexAura shares a
daily generation quota of roughly 20 with real production traffic.

Checks: `availability`, `retrieval_hit_rate` (deterministic, known passage present in retrieved
context), `citation_integrity` (deterministic, required citation present), `faithfulness`
(LLM-judge, every claim checked against retrieved context), `p95_latency_ms`.

### SENTINEL: agent outcome integrity

Runs against the 8 seeded typology scenarios already loaded in SENTINEL's own database,
triggering each investigation's real five-agent workflow and polling it to completion.

Checks: `availability`, `typology_accuracy`, `typology_precision`, `pipeline_completion_rate`
(full LLM path vs. rule-based fallback), `sar_schema_validity`, `p95_latency_ms`.

Full scoring detail for all three suites, the versioned judge prompt, and known limitations are
on the [methodology page](https://nokware.vercel.app/methodology).

## Honesty rules

Enforced by how the code is structured, not by a policy someone could forget to follow:

1. Regressions publish automatically; no hide-a-run path exists in code.
2. Every score links to raw traces.
3. LLM-judged scores display judge-verification status (gated by a meta-eval against a
   hand-labeled fixture set; scores below 85% judge agreement publish flagged unverified,
   never hidden).
4. Last 90 days shown unedited.

## Quickstart

No secrets required to run the harness against the live public APIs it targets:

```bash
git clone https://github.com/PatrickAttankurugu/nokware.git
cd nokware
pip install -e ".[dev]"
nokware run --suite africapep --dry-run
```

`nokware run` must be invoked from the repo root: it reads `golden/*.jsonl` and
`prompts/faithfulness.txt` via paths relative to the current working directory.

This calls the live AfricaPEP API with its 108-entry golden set and prints each check's score,
with no database write (`--dry-run`) and no API key needed (AfricaPEP's auth middleware is
currently disabled in production). Swap `africapep` for `lexaura` or `sentinel`, or pass `--all`
to run every suite. `pytest -v` runs the full test suite offline (no live network calls; two
database-dependent tests skip without `TEST_DATABASE_URL`).

Every golden entry in `golden/africapep.jsonl` is verifiable independently:

```bash
AFRICAPEP_BASE_URL=https://api-pep.patrickaiafrica.com AFRICAPEP_API_KEY=unused \
  python scripts/verify_golden.py golden/africapep.jsonl
```

## MCP server

`nokware-mcp` exposes the ledger (`get_scores`, `get_run_detail`, `list_incidents`,
`trigger_run`) to Claude Code or any MCP client. Setup, tool reference, and required env vars:
[`docs/mcp.md`](docs/mcp.md).

## Custom domain

The intended production URL is `nokware.patrickaiafrica.com`. That requires a Namecheap DNS
change only Patrick can make: a `CNAME` record for the `nokware` subdomain pointing at
`cname.vercel-dns.com`, plus adding the domain to the Vercel project. Until that DNS change
lands, the dashboard is reachable at the Vercel-assigned URL above.

## License

MIT. See [LICENSE](LICENSE).
