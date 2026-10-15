"""JSON file store + metrics log."""
from __future__ import annotations
import json, os, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "store"
STORE.mkdir(parents=True, exist_ok=True)
DOCS = STORE / "docs.jsonl"
REVIEWS = STORE / "reviews.jsonl"
METRICS = STORE / "metrics.jsonl"


def _append(path: Path, obj: dict) -> None:
    obj = {"ts": time.time(), **obj}
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")


def save_doc(obj: dict) -> None: _append(DOCS, obj)
def queue_review(obj: dict) -> None: _append(REVIEWS, obj)
def log_metric(obj: dict) -> None: _append(METRICS, obj)


def read_all(path: Path, limit: int = 200) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-limit:]
    out = []
    for ln in lines:
        try: out.append(json.loads(ln))
        except Exception: continue
    return out


def resolve_review(doc_id: str, decision: str, reviewer: str) -> bool:
    items = read_all(REVIEWS, 1000)
    found = False
    remaining = []
    for it in items:
        if it.get("doc_id") == doc_id and it.get("status") == "open":
            it["status"] = decision; it["reviewer"] = reviewer; found = True
        remaining.append(it)
    REVIEWS.write_text("\n".join(json.dumps(x) for x in remaining) + ("\n" if remaining else ""))
    return found
