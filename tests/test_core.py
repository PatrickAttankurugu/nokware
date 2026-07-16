from nokware.core import Check, CheckResult, Suite


def ok_check() -> CheckResult:
    return CheckResult(check_id="c1", suite="s", score_type="deterministic",
                       value=1.0, passed=True, traces={})


def boom_check() -> CheckResult:
    raise RuntimeError("api down")


def test_suite_runs_checks_and_captures_errors():
    suite = Suite(name="s", checks=[
        Check(id="c1", suite="s", description="ok", fn=ok_check),
        Check(id="c2", suite="s", description="boom", fn=boom_check),
    ])
    results = suite.run()
    assert len(results) == 2
    assert results[0].passed is True
    assert results[1].passed is False and results[1].value == 0.0
    assert "api down" in results[1].traces["error"]
