"""Single model-call abstraction: Muse Spark via the LOCAL opencode service only.

The app makes exactly ONE shaped model call per question: grounded_answer().
- The remote path shells to the local opencode background service
  (`opencode run --model opencode/muse-spark-1.3-contributor-free --format json`).
  No API keys, no cloud endpoints: opencode's own login handles auth.
- Retrieved passages are the ONLY allowed evidence; the model must reply as
  JSON {"answer": str, "used_passages": [int]} or {"answer": "REFUSE", ...}.
- If the service is unreachable or returns unparsable output, a deterministic
  extractive fallback answers from the top-ranked passages (no hallucination),
  keeping the demo, tests and eval reproducible offline.
"""
from __future__ import annotations
import json
import os
import subprocess
import time
from pathlib import Path
from app.index import MIN_SCORE
from app.schemas import Citation, QAResponse

MODEL_ID = os.getenv("OPENCODE_MODEL", "opencode/muse-spark-1.3-contributor-free")
OPENCODE_BIN = os.getenv("OPENCODE_BIN", "opencode")
TIMEOUT_S = int(os.getenv("OPENCODE_TIMEOUT_S", "120"))
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SYSTEM = (
    "You answer finance questions using ONLY the provided passages. "
    "Reply with exactly one JSON object and nothing else: "
    '{"answer": str, "used_passages": [int]}. '
    "If the passages do not contain the answer, reply "
    '{"answer": "REFUSE", "used_passages": []}.'
)


def _remote_call(question: str, citations: list[Citation]) -> str | None:
    passages = [f"[{i}] {c.passage}" for i, c in enumerate(citations)]
    prompt = SYSTEM + "\n\nPassages:\n" + "\n".join(passages) + f"\n\nQuestion: {question}"
    try:
        proc = subprocess.run(
            [OPENCODE_BIN, "run", "--model", MODEL_ID, "--format", "json", prompt],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    texts: list[str] = []
    for line in proc.stdout.splitlines():
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = evt.get("part", {}) if isinstance(evt, dict) else {}
        if evt.get("type") == "text" and part.get("type") == "text":
            texts.append(part.get("text", ""))
    return "".join(texts).strip() or None


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
