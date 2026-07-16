import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

from nokware.db import Ledger

mcp = FastMCP("nokware")

REPO = "PatrickAttankurugu/nokware"


def _ledger() -> Ledger:
    # NEON_DATABASE_URL is read lazily, only when a tool is actually invoked, so the
    # server can be launched (and its tool list introspected) from any working
    # directory and without the env var set, per the CWD-safety amendment.
    return Ledger(os.environ["NEON_DATABASE_URL"])


@mcp.tool()
def get_scores(system: str | None = None) -> str:
    """Latest score per check, optionally filtered to one system (africapep|lexaura|sentinel)."""
    with _ledger()._conn() as conn:
        q = """SELECT DISTINCT ON (suite, check_id) suite, check_id, value, passed,
                      baseline, created_at::text
               FROM results {where} ORDER BY suite, check_id, created_at DESC"""
        if system:
            rows = conn.execute(q.format(where="WHERE suite = %s"), (system,)).fetchall()
        else:
            rows = conn.execute(q.format(where="")).fetchall()
    cols = ["suite", "check_id", "value", "passed", "baseline", "created_at"]
    return json.dumps([dict(zip(cols, r)) for r in rows], default=str)


@mcp.tool()
def get_run_detail(run_id: int) -> str:
    """Full results and traces for one run."""
    with _ledger()._conn() as conn:
        run_cur = conn.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
        run_row = run_cur.fetchone()
        run_cols = [d.name for d in run_cur.description]
        results_cur = conn.execute(
            "SELECT check_id, suite, value, passed, traces FROM results WHERE run_id = %s",
            (run_id,))
        result_cols = [d.name for d in results_cur.description]
        results = results_cur.fetchall()
    run = dict(zip(run_cols, run_row)) if run_row else None
    return json.dumps(
        {"run": run, "results": [dict(zip(result_cols, r)) for r in results]},
        default=str,
    )


@mcp.tool()
def list_incidents(state: str | None = None) -> str:
    """Incidents, optionally filtered by state (investigating|explained|resolved)."""
    with _ledger()._conn() as conn:
        if state:
            cur = conn.execute(
                "SELECT * FROM incidents WHERE state = %s ORDER BY opened_at DESC LIMIT 50",
                (state,))
        else:
            cur = conn.execute(
                "SELECT * FROM incidents ORDER BY opened_at DESC LIMIT 50")
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return json.dumps([dict(zip(cols, r)) for r in rows], default=str)


def trigger_run_impl(suite: str) -> str:
    token = os.environ.get("GH_DISPATCH_TOKEN")
    if not token:
        return "error: GH_DISPATCH_TOKEN is not set; trigger_run requires it"
    resp = httpx.post(
        f"https://api.github.com/repos/{REPO}/actions/workflows/nightly.yml/dispatches",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json={"ref": "main", "inputs": {"suite": suite}}, timeout=30)
    return "run dispatched" if resp.status_code == 204 else f"error: {resp.status_code} {resp.text}"


@mcp.tool()
def trigger_run(suite: str = "all") -> str:
    """Dispatch an eval run via GitHub Actions. Requires GH_DISPATCH_TOKEN."""
    return trigger_run_impl(suite)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
