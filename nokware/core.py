from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel


class CheckResult(BaseModel):
    check_id: str
    suite: str
    score_type: Literal["deterministic", "statistical", "llm_judge"]
    value: float
    passed: bool
    traces: dict = {}


@dataclass
class Check:
    id: str
    suite: str
    description: str
    fn: Callable[[], CheckResult]


@dataclass
class Suite:
    name: str
    checks: list[Check]

    def run(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for check in self.checks:
            try:
                results.append(check.fn())
            except Exception as e:  # a crashed check is a failed check, never a crashed run
                results.append(CheckResult(
                    check_id=check.id, suite=self.name, score_type="deterministic",
                    value=0.0, passed=False, traces={"error": f"{type(e).__name__}: {e}"},
                ))
        return results
