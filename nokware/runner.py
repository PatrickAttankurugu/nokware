import argparse
import datetime as dt
import os
import subprocess
import sys
from typing import Callable

from nokware.core import CheckResult, Suite
from nokware.db import Ledger


class JudgeBudget:
    def __init__(self, limit: int = 200):
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def _build_africapep() -> Suite:
    from suites.africapep import build_suite
    return build_suite(os.environ.get("AFRICAPEP_BASE_URL", "https://api-pep.patrickaiafrica.com"),
                       os.environ.get("AFRICAPEP_API_KEY", "unused"))


SUITE_BUILDERS: dict[str, Callable[[], Suite]] = {
    "africapep": _build_africapep,
    # "lexaura" registered in Task 11, "sentinel" in Task 12
}


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def golden_hash() -> str:
    try:
        return subprocess.check_output(["git", "log", "-1", "--format=%h", "--", "golden/"],
                                       text=True).strip() or "none"
    except Exception:
        return "unknown"


def write_summary(results: list[CheckResult], path: str) -> None:
    lines = [f"# Nokware run {dt.date.today().isoformat()}", ""]
    for suite in sorted({r.suite for r in results}):
        lines.append(f"## {suite}")
        for r in [x for x in results if x.suite == suite]:
            lines.append(f"- {r.check_id}: {r.value} {'PASS' if r.passed else 'FAIL'}")
        lines.append("")
    with open(path, "w", encoding="utf8") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(prog="nokware")
    sub = ap.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run")
    runp.add_argument("--suite")
    runp.add_argument("--all", action="store_true")
    runp.add_argument("--dry-run", action="store_true")
    initp = sub.add_parser("init-db")
    args = ap.parse_args()

    if args.cmd == "init-db":
        Ledger(os.environ["NEON_DATABASE_URL"]).init_schema()
        print("schema ready")
        return 0

    names = list(SUITE_BUILDERS) if args.all else [args.suite]
    if not names or names == [None]:
        print("error: pass --suite NAME or --all", file=sys.stderr)
        return 2
    unknown = [n for n in names if n not in SUITE_BUILDERS]
    if unknown:
        print(f"error: unknown suite(s) {unknown}; known: {list(SUITE_BUILDERS)}", file=sys.stderr)
        return 2

    results: list[CheckResult] = []
    for name in names:
        results.extend(SUITE_BUILDERS[name]().run())

    for r in results:
        print(f"{r.suite}/{r.check_id}: {r.value} {'PASS' if r.passed else 'FAIL'}")

    if not args.dry_run:
        ledger = Ledger(os.environ["NEON_DATABASE_URL"])
        run_id = ledger.start_run(git_sha(), golden_hash(),
                                  trigger=os.environ.get("NOKWARE_TRIGGER", "manual"))
        baselines = ledger.write_results(run_id, results)
        from nokware.drift import is_drift
        LATENCY_CHECKS = {"p95_latency_ms"}
        for r in results:
            base = baselines.get((r.suite, r.check_id))
            if is_drift(r.value, base, higher_is_worse=r.check_id in LATENCY_CHECKS):
                ledger.open_incident(run_id, r.suite, r.check_id, severity="regression",
                                     root_cause_hint=f"value {r.value} vs 7d baseline {round(base, 4)}")
        judge_verified, judge_agreement = True, None
        if any(r.score_type == "llm_judge" for r in results):
            from nokware.judge import Judge
            from nokware.meta_eval import run_meta_eval
            meta_judge = Judge(api_key=os.environ.get("GEMINI_API_KEY"), budget=JudgeBudget(limit=40))
            judge_agreement = run_meta_eval(meta_judge)
            judge_verified = judge_agreement >= 0.85
        ledger.finish_run(run_id, status="completed",
                          judge_verified=judge_verified, judge_agreement=judge_agreement)
        os.makedirs("runs", exist_ok=True)
        write_summary(results, f"runs/{dt.date.today().isoformat()}.md")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
