# Nokware MCP server

`nokware-mcp` exposes the reliability ledger to Claude Code (or any MCP client) as four
tools, backed by the same `Ledger` (`nokware/db.py`) the runner writes to and the same
GitHub Actions workflow (`nightly.yml`) the nightly loop dispatches.

## Requirements

- The server reads only the database and GitHub's API. It does not read any file
  relative to its working directory, so it can be launched from anywhere.
- **`NEON_DATABASE_URL` is required** in the MCP client's env config for `get_scores`,
  `get_run_detail`, and `list_incidents` to work. It is read lazily (only when a tool
  is called), so the server still starts and lists its tools without it set; calls to
  those three tools will fail if it is missing.
- `trigger_run` additionally requires `GH_DISPATCH_TOKEN` (a GitHub token with
  `actions:write` on `PatrickAttankurugu/nokware`). Without it, the tool returns a
  clear error string instead of raising.

## Setup (Claude Code)

Run this once the package is installed (`pip install -e .`, which puts `nokware-mcp` on
the venv's PATH):

```bash
claude mcp add nokware -e NEON_DATABASE_URL=<neon-dsn> -e GH_DISPATCH_TOKEN=<token> -- nokware-mcp
```

If `nokware-mcp` is not on PATH (e.g. running from outside the project venv), point at
the venv's script directly instead, e.g. on Windows:

```bash
claude mcp add nokware -e NEON_DATABASE_URL=<neon-dsn> -e GH_DISPATCH_TOKEN=<token> -- C:/path/to/nokware/.venv312/Scripts/nokware-mcp
```

`GH_DISPATCH_TOKEN` is optional if you only need read tools (`get_scores`,
`get_run_detail`, `list_incidents`); it is required for `trigger_run`.

After adding, verify inside a Claude session by calling `get_scores` (with no
arguments) and confirming it returns without error (an empty list is expected until
the first nightly run has written results).

## Tools

### `get_scores(system: str | None = None) -> str`

Returns a JSON array of the latest score per `(suite, check_id)`, each entry a dict
with keys `suite`, `check_id`, `value`, `passed`, `baseline`, `created_at`. Pass
`system` (`africapep`, `lexaura`, or `sentinel`) to filter to one suite.

### `get_run_detail(run_id: int) -> str`

Returns a JSON object `{"run": {...} | null, "results": [{...}, ...]}`. `run` is the
full `runs` row as a dict (or `null` if the run id doesn't exist); each entry in
`results` is a dict with keys `check_id`, `suite`, `value`, `passed`, `traces`.

### `list_incidents(state: str | None = None) -> str`

Returns a JSON array of up to 50 incident rows (most recent first), each a dict of
every `incidents` column. Pass `state` (`investigating`, `explained`, or `resolved`)
to filter.

### `trigger_run(suite: str = "all") -> str`

Dispatches the `nightly.yml` GitHub Actions workflow on `main` with input
`{"suite": suite}`, using `GH_DISPATCH_TOKEN` as a bearer token. Returns
`"run dispatched"` on success (GitHub responds `204`), or an `"error: ..."` string
(never an exception) if the token is missing or the dispatch call fails.

## Repo constant

The server dispatches against `PatrickAttankurugu/nokware` (the `REPO` constant in
`nokware/mcp_server.py`). That GitHub repo does not exist yet as of this writing
(Task 6 creates it) -- `trigger_run` will return an `error: 404 ...` string until then,
which is the expected, non-crashing failure mode.
