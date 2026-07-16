from nokware.judge import Judge
from nokware.meta_eval import run_meta_eval
from nokware.runner import JudgeBudget


def test_fallback_judge_agreement_is_measurable():
    judge = Judge(api_key=None, budget=JudgeBudget(limit=100))
    agreement = run_meta_eval(judge, "golden/judge.jsonl")
    assert 0.0 <= agreement <= 1.0
