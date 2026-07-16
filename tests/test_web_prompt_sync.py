"""The public methodology page renders web/prompts/faithfulness.txt; the judge
runs prompts/faithfulness.txt. They are two files for Vercel packaging reasons
and MUST stay byte-identical, or the public page lies about the running judge."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_methodology_prompt_matches_judge_prompt():
    canonical = (ROOT / "prompts" / "faithfulness.txt").read_text(encoding="utf8")
    web_copy = (ROOT / "web" / "prompts" / "faithfulness.txt").read_text(encoding="utf8")
    assert canonical == web_copy, (
        "web/prompts/faithfulness.txt has drifted from prompts/faithfulness.txt; "
        "copy the canonical file over the web copy"
    )
