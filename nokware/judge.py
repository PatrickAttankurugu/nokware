import json
import pathlib
import re
from typing import Literal

from pydantic import BaseModel

from nokware.runner import JudgeBudget

PROMPT = (pathlib.Path(__file__).resolve().parent.parent / "prompts" / "faithfulness.txt").read_text(encoding="utf8")
STOPWORDS = {"the", "a", "an", "is", "are", "of", "to", "and", "in", "for", "on"}


class JudgeVerdict(BaseModel):
    supported: bool
    score: float
    reasons: list[str] = []
    engine: Literal["gemini", "fallback"]


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS}


def keyword_overlap(answer: str, context: str) -> float:
    a, c = _tokens(answer), _tokens(context)
    if not a:
        return 0.0
    return len(a & c) / len(a)


class Judge:
    def __init__(self, api_key: str | None, budget: JudgeBudget):
        self.api_key = api_key
        self.budget = budget

    def _fallback(self, answer: str, context: str,
                 reason: str = "keyword-overlap fallback") -> JudgeVerdict:
        score = keyword_overlap(answer, context)
        return JudgeVerdict(supported=score >= 0.5, score=round(score, 4),
                            reasons=[reason], engine="fallback")

    def judge_faithfulness(self, answer: str, context: str) -> JudgeVerdict:
        # The reason a call fell back to the deterministic engine is worth
        # keeping distinct: "no_api_key" and "budget_exhausted" are both
        # operational visibility signals (misconfiguration vs. spend), not the
        # same generic "we used the fallback" reason a Gemini error produces.
        if not self.api_key:
            return self._fallback(answer, context, reason="no_api_key")
        # budget counts attempts, not successes: API cost is incurred per call attempt
        if not self.budget.take():
            return self._fallback(answer, context, reason="budget_exhausted")
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            prompt = PROMPT.replace("{answer}", answer).replace("{context}", context)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            payload = json.loads(re.search(r"\{.*\}", resp.text, re.S).group(0))
            claims = payload["claims"]
            supported = [c for c in claims if c.get("supported")]
            score = len(supported) / len(claims) if claims else 0.0
            return JudgeVerdict(
                supported=score >= 0.8, score=round(score, 4),
                reasons=[c["claim"] for c in claims if not c.get("supported")][:5],
                engine="gemini")
        except Exception as e:
            v = self._fallback(answer, context)
            v.reasons.append(f"gemini error: {type(e).__name__}")
            return v
