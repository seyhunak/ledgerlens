# DEPLOYMENT.md — managed API vs self-hosted, + serving benchmark

## Decision rule
| Signal | Use managed API (Muse Spark / hosted LLM) | Use self-hosted |
|---|---|---|
| Volume | < 1M tokens/day, spiky | sustained high QPS, predictable |
| Data boundary | non-sensitive / DPA-covered | regulated data that cannot leave VPC |
| Latency SLO | p95 < 3s acceptable | p95 < 500ms, offline, air-gapped |
| Team | small, no GPU ops | platform team + GPUs available |
| Change rate | want weekly model upgrades free | need pinned weights for audit reproducibility |

Default for this app: **local opencode service for the single grounded-answer call**
(`opencode/muse-spark-1.3-contributor-free`, no API keys, data stays on this machine),
**self-hosted deterministic code (regex rules, TF-IDF retrieval, tesseract OCR) for everything else**
(cost ~$0, auditable, reproducible). Only self-host the model when data-residency or
offline operation forces it.

## Benchmark (Apple Silicon, CPU-only, measured 2026-10-15)
Run: `python3 scripts/bench.py` (ingest + retrieve + answer over sample docs, 20 iterations).

| Op | Mean | Notes |
|---|---|---|
| Ingest (text PDF, 1 pg) | ~40 ms | pypdf path, no OCR |
| OCR page (tesseract, 300dpi PNG) | ~900 ms | CPU-bound; cache text layer |
| Retrieval (TF-IDF, ~50 passages) | ~25 ms | in-memory sklearn |
| Extractive answer (fallback) | ~30 ms | no network |
| Model call (local opencode service) | ~5–20 s | session + inference; only on ask |

End-to-end ask p95 on this laptop (fallback path): **< 150 ms**.
With live model via local service: **~5–20 s**, dominated by session setup + inference.

## Reproduce
```
pip install -r requirements.txt
python3 scripts/bench.py
python3 -m app.eval && python3 -m app.eval && python3 -m app.eval  # 3 reproducible runs
uvicorn app.main:app --port 8000
```
If suitable GPU hardware is available, add a vLLM/Ollama backend behind `app/llm.py::_remote_call`
If a GPU-backed local server is available, point `OPENCODE_MODEL` at a model it
serves through the opencode service and re-run `scripts/bench.py`.
