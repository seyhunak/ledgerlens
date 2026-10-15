"""Single model-call abstraction (Muse Spark 1.3 Free via opencode, with safe fallback).

The app makes exactly ONE shaped model call per question: grounded_answer().
- If SPARK_API_KEY (or ANTHROPIC_API_KEY) is set, it calls the chat API with
  retrieved passages as the ONLY allowed evidence and JSON tool-style output.
- Otherwise it uses a deterministic extractive fallback (no hallucination),
  which keeps the demo, tests and eval fully reproducible offline.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from app.index import MIN_SCORE
from app.schemas import Citation, QAResponse

MODEL_ID = "muse-spark-1.3-free"
SYSTEM = (
    "You answer finance questions using ONLY the provided passages. "
    "Reply as JSON {\"answer\": str, \"used_passages\": [int]}. "
    "If the passages do not contain the answer, reply {\"answer\": \"REFUSE\", \"used_passages\": []}."
)


def _remote_call(question: str, citations: list[Citation]) -> str | None:
    key = os.getenv("SPARK_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    base = os.getenv("SPARK_API_BASE", "https://api.anthropic.com/v1/messages")
    if not key:
        return None
    passages = [f"[{i}] {c.passage}" for i, c in enumerate(citations)]
    body = json.dumps({
        "model": os.getenv("SPARK_MODEL", MODEL_ID),
        "max_tokens": 400,
        "system": SYSTEM,
        "messages": [{"role": "user",
                      "content": f"Passages:\n" + "\n".join(passages) + f"\n\nQuestion: {question}"}],
    }).encode()
    try:
        req = urllib.request.Request(base, data=body, headers={
            "Content-Type": "application/json",
            "x-api-key": key, "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        return resp["content"][0]["text"]
    except Exception:
        return None


def grounded_answer(question: str, citations: list[Citation]) -> QAResponse:
    t0 = time.time()
    if not citations or max((c.score for c in citations), default=0) < MIN_SCORE:
        return QAResponse(answer="I don't have sufficient evidence in the uploaded documents to answer that.",
                          citations=[], grounded=False, refused=True,
                          latency_ms=int((time.time() - t0) * 1000), model="refusal-gate")
    raw = _remote_call(question, citations)
    used = list(range(len(citations)))
    if raw:
        try:
            parsed = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
            if parsed.get("answer") == "REFUSE":
                return QAResponse(answer="I don't have sufficient evidence in the uploaded documents to answer that.",
                                  citations=[], grounded=False, refused=True,
                                  latency_ms=int((time.time() - t0) * 1000), model=MODEL_ID)
            used = [int(i) for i in parsed.get("used_passages", used) if 0 <= int(i) < len(citations)]
            answer = str(parsed.get("answer", "")).strip() or _extractive(citations)
            return QAResponse(answer=answer, citations=[citations[i] for i in used],
                              grounded=True, refused=False,
                              latency_ms=int((time.time() - t0) * 1000), model=MODEL_ID)
        except Exception:
            pass
    # Deterministic extractive fallback: stitch top sentences containing query terms.
    answer = _extractive(citations)
    return QAResponse(answer=answer, citations=citations[:2], grounded=True, refused=False,
                      latency_ms=int((time.time() - t0) * 1000), model="deterministic-fallback")


def _extractive(citations: list[Citation]) -> str:
    import re
    sents: list[str] = []
    for c in citations[:2]:
        sents += [s.strip() for s in re.split(r"(?<=[.!?])\s+", c.passage) if len(s.strip()) > 20][:2]
    return "Based on the documents: " + " ".join(sents[:3])
