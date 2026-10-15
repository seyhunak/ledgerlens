"""FastAPI: ingestion, extraction, grounded QA, human review, metrics, eval."""
from __future__ import annotations
import os
import re
import time, uuid
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import store
from app.auth import check_access, require_reviewer
from app.extract import classify, extract_invoice, extract_policy
from app.index import chunk, retrieve
from app.llm import grounded_answer
from app.ocr import extract_text
from app.rules import run_rules
from app.schemas import IngestResponse, RuleFinding
from app.security import (RequestIDMiddleware, SecurityHeadersMiddleware,
                          RateLimitMiddleware, audit)

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
ALLOWED_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".txt")

app = FastAPI(title="Enterprise Financial Document Intelligence", version="1.1.0",
              docs_url="/api/docs", redoc_url=None)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors:
    app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["GET", "POST"],
                       allow_headers=["X-API-Key", "X-Role", "X-Request-ID"])
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

# In-memory corpus (rebuilt from store on demand is overkill for demo)
CORPUS: list[dict] = []
DOC_TEXTS: dict[str, str] = {}


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/ready")
def ready():
    checks = {"store_writable": False, "uploads_writable": False}
    try:
        probe = store.STORE / ".probe"
        probe.write_text("ok"); probe.unlink(missing_ok=True)
        checks["store_writable"] = True
    except Exception:
        pass
    checks["uploads_writable"] = UPLOADS.is_dir()
    if not all(checks.values()):
        return JSONResponse({"ready": False, "checks": checks}, status_code=503)
    return {"ready": True, "checks": checks}


def _safe_filename(name: str) -> str:
    base = Path(name).name  # strip directories
    clean = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120]
    if "." not in clean:
        clean += ".bin"
    return clean


@app.get("/", response_class=HTMLResponse)
def ui(request: Request):
    docs = store.read_all(store.DOCS, 50)
    reviews = [r for r in store.read_all(store.REVIEWS, 100) if r.get("status") == "open"]
    metrics = store.read_all(store.METRICS, 200)
    n = len(metrics)
    avg_ms = int(sum(m.get("latency_ms", 0) for m in metrics) / n) if n else 0
    return templates.TemplateResponse(request, "index.html", {
        "docs": docs[::-1][:10], "reviews": reviews[::-1],
        "metric_count": n, "avg_ms": avg_ms,
        "api_key": "demo-key-123",
    })


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...),
                 role: str = Depends(check_access),
                 x_api_key: str | None = Header(default=None)):
    t0 = time.time()
    fname = _safe_filename(file.filename or "")
    if not fname.lower().endswith(ALLOWED_EXTS):
        raise HTTPException(400, "Only PDF / image / TXT accepted")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES} bytes)")
    doc_id = uuid.uuid4().hex[:10]
    dest = UPLOADS / f"{doc_id}_{fname}"
    dest.write_bytes(raw)
    try:
        text, pages, ocr_used = extract_text(str(dest), file.filename)
    except Exception as e:
        raise HTTPException(400, f"Extraction failed: {e}")
    if len(text.strip()) < 20:
        raise HTTPException(422, "No readable text found (scan quality too low?)")
    dtype = classify(text)
    if dtype == "invoice":
        ext = extract_invoice(text)
        rules = run_rules(ext)
        payload = ext.model_dump()
    else:
        ext = extract_policy(text)
        rules = [RuleFinding(rule="required_fields",
                             passed=not ext.missing_fields,
                             detail="missing: " + ", ".join(ext.missing_fields) if ext.missing_fields else "policy fields present")]
        payload = ext.model_dump()
    needs_review = any(not r.passed for r in rules)
    ms = int((time.time() - t0) * 1000)
    store.save_doc({"doc_id": doc_id, "filename": fname, "doc_type": dtype,
                    "pages": pages, "chars": len(text), "ocr_used": ocr_used,
                    "needs_review": needs_review, "role": role})
    audit("doc.ingested", doc_id=doc_id, doc_type=dtype, needs_review=needs_review, role=role)
    if needs_review:
        store.queue_review({"doc_id": doc_id, "filename": fname,
                            "reasons": [r.detail for r in rules if not r.passed],
                            "status": "open"})
    DOC_TEXTS[doc_id] = text
    CORPUS.extend(chunk(text, doc_id))
    store.log_metric({"op": "ingest", "doc_id": doc_id, "latency_ms": ms,
                      "ocr_used": ocr_used, "role": role, "est_cost_usd": 0.002 if ocr_used else 0.0005})
    return IngestResponse(doc_id=doc_id, filename=fname, doc_type=dtype, pages=pages,
                          chars=len(text), ocr_used=ocr_used, extraction=payload,
                          rules=rules, needs_review=needs_review, latency_ms=ms)


@app.post("/api/ask")
async def ask(question: str = Form(...), role: str = Depends(check_access)):
    t0 = time.time()
    cits = retrieve(question, CORPUS)
    resp = grounded_answer(question, cits)
    ms = int((time.time() - t0) * 1000)
    resp.latency_ms = ms
    store.log_metric({"op": "ask", "latency_ms": ms, "grounded": resp.grounded,
                      "refused": resp.refused, "model": resp.model, "est_cost_usd": 0.001})
    return resp.model_dump()


@app.get("/api/reviews")
def list_reviews(role: str = Depends(check_access)):
    return [r for r in store.read_all(store.REVIEWS, 200) if r.get("status") == "open"]


@app.post("/api/reviews/{doc_id}/resolve")
def resolve(doc_id: str, decision: str = Form(...), reviewer: str = Form(default="reviewer"),
            role: str = Depends(check_access), x_api_key: str | None = Header(default=None)):
    require_reviewer(role, x_api_key)  # critical action: authorisation mandatory
    if decision not in ("approved", "rejected", "corrected"):
        raise HTTPException(400, "decision must be approved|rejected|corrected")
    ok = store.resolve_review(doc_id, decision, reviewer)
    store.log_metric({"op": "review_resolve", "doc_id": doc_id, "decision": decision,
                      "latency_ms": 0, "est_cost_usd": 0})
    audit("review.resolved", doc_id=doc_id, decision=decision, reviewer=reviewer)
    if not ok:
        raise HTTPException(404, "No open review for that doc")
    return {"doc_id": doc_id, "decision": decision}


@app.get("/api/metrics")
def metrics(role: str = Depends(check_access)):
    m = store.read_all(store.METRICS, 500)
    ops: dict[str, dict] = {}
    for x in m:
        o = ops.setdefault(x.get("op", "?"), {"n": 0, "ms": 0, "cost": 0.0})
        o["n"] += 1; o["ms"] += x.get("latency_ms", 0); o["cost"] += x.get("est_cost_usd", 0)
    summary = {k: {"calls": v["n"], "avg_latency_ms": int(v["ms"] / v["n"]),
                   "est_cost_usd": round(v["cost"], 4)} for k, v in ops.items()}
    return {"summary": summary, "recent": m[-50:]}
