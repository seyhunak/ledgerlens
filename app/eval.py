"""Versioned evaluation: extraction, retrieval, groundedness, refusal, auth."""
from __future__ import annotations
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.extract import extract_invoice
from app.index import chunk, retrieve, MIN_SCORE
from app.llm import grounded_answer
from app.rules import run_rules

TESTSET = ROOT / "tests" / "testset.v1.json"


def run() -> dict:
    cases = json.loads(TESTSET.read_text())
    res = {"version": "v1", "n": len(cases), "passed": 0, "failures": [],
           "by_category": {}, "ts": time.time()}
    corpus: list[dict] = []
    for c in cases:
        if c["category"] in ("extraction", "rules") and c.get("text"):
            corpus.extend(chunk(c["text"], c["id"]))
    for c in cases:
        cat = c["category"]
        ok = False
        try:
            if cat == "extraction":
                ext = extract_invoice(c["text"])
                d = ext.model_dump()
                ok = all(d.get(k) == v for k, v in c["expect"].items())
            elif cat == "rules":
                ext = extract_invoice(c["text"])
                rules = {r.rule: r.passed for r in run_rules(ext, **c.get("policy", {}))}
                ok = all(rules.get(k) == v for k, v in c["expect_rules"].items())
            elif cat == "grounded_qa":
                cits = retrieve(c["question"], corpus)
                ans = grounded_answer(c["question"], cits)
                ok = (ans.grounded and not ans.refused
                      and any(k.lower() in ans.answer.lower() for k in c["must_contain"])
                      and len(ans.citations) > 0
                      and max(x.score for x in ans.citations) >= MIN_SCORE)
            elif cat == "refusal":
                cits = retrieve(c["question"], corpus)
                ans = grounded_answer(c["question"], cits)
                ok = ans.refused and not ans.grounded
            elif cat == "auth":
                from app.auth import require_reviewer
                from fastapi import HTTPException
                try:
                    require_reviewer("analyst", "demo-key-123")
                    ok = c["expect"] == "allowed"
                except HTTPException:
                    ok = c["expect"] == "denied"
        except Exception as e:
            ok = False
            c = {**c, "error": str(e)}
        res["by_category"].setdefault(cat, {"n": 0, "passed": 0})
        res["by_category"][cat]["n"] += 1
        if ok:
            res["passed"] += 1; res["by_category"][cat]["passed"] += 1
        else:
            res["failures"].append(c["id"])
    res["accuracy"] = round(res["passed"] / res["n"], 3) if res["n"] else 0
    return res


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    Path(ROOT / "data" / "store" / "eval_last.json").write_text(json.dumps(r, indent=2))
