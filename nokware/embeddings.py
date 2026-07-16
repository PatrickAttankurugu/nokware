import json

from nokware.core import CheckResult


def embed_text(text: str, api_key: str | None) -> list[float] | None:
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        resp = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        return list(resp.embeddings[0].values)
    except Exception:
        return None


def failure_signature(result: CheckResult) -> str:
    return json.dumps({"suite": result.suite, "check": result.check_id,
                       "traces": result.traces}, sort_keys=True)[:2000]


def assign_cluster(ledger, result_id: int, embedding: list[float],
                   threshold: float = 0.85) -> int:
    with ledger._conn() as conn:
        row = conn.execute(
            """SELECT id, 1 - (embedding <=> %s::vector) AS sim
               FROM results WHERE embedding IS NOT NULL AND passed = false AND id <> %s
               ORDER BY embedding <=> %s::vector LIMIT 1""",
            (json.dumps(embedding), result_id, json.dumps(embedding)),
        ).fetchone()
        if row and row[1] is not None and row[1] >= threshold:
            return row[0]
        return result_id
