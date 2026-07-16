"""web/src/app/systems/[slug]/page.tsx's HIGHER_IS_WORSE_CHECKS drives which
checks the dashboard displays with a "higher is worse" unit/trend direction.
nokware/runner.py's LATENCY_CHECKS drives which checks the drift detector
inverts its comparison for. Both sets encode the same fact (which checks get
worse when the value goes up) in two different languages, so this test
parses each source file's set literal with a regex (no import needed on
either side, since one is TypeScript) and asserts they name the exact same
checks. If they drift apart, the dashboard and the drift detector would
silently disagree about which direction is a regression."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _extract_string_set(text: str, pattern: str) -> set[str]:
    match = re.search(pattern, text)
    assert match, f"could not find pattern {pattern!r} in source"
    return set(re.findall(r"""["']([^"']+)["']""", match.group(1)))


def test_higher_is_worse_checks_match_latency_checks():
    web_src = (ROOT / "web" / "src" / "app" / "systems" / "[slug]" / "page.tsx").read_text(
        encoding="utf8"
    )
    runner_src = (ROOT / "nokware" / "runner.py").read_text(encoding="utf8")

    web_checks = _extract_string_set(
        web_src, r"HIGHER_IS_WORSE_CHECKS\s*=\s*new Set\(\[(.*?)\]\)"
    )
    runner_checks = _extract_string_set(runner_src, r"LATENCY_CHECKS\s*=\s*\{(.*?)\}")

    assert web_checks == runner_checks, (
        f"web HIGHER_IS_WORSE_CHECKS {web_checks} != runner LATENCY_CHECKS {runner_checks}; "
        "keep the two lists identical"
    )
