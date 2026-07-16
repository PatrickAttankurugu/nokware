import json

from nokware.judge import Judge


def run_meta_eval(judge: Judge, fixtures_path: str = "golden/judge.jsonl") -> float:
    fixtures = [json.loads(l) for l in open(fixtures_path, encoding="utf8") if l.strip()]
    if not fixtures:
        return 0.0
    hits = 0
    for f in fixtures:
        verdict = judge.judge_faithfulness(f["answer"], f["context"])
        if verdict.supported == f["supported"]:
            hits += 1
    return hits / len(fixtures)
