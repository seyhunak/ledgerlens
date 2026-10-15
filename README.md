# LedgerLens — Enterprise Financial Document Intelligence

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Eval v1: 12/12](https://img.shields.io/badge/eval%20v1-12%2F12-brightgreen)](tests/testset.v1.json)
[![OCR: pypdf + tesseract](https://img.shields.io/badge/OCR-pypdf%20%2B%20tesseract-lightgrey)](app/ocr.py)
[![Model: Muse Spark 1.3 Free](https://img.shields.io/badge/model-Muse%20Spark%201.3%20Free-violet)](app/llm.py)
[![Docker](https://img.shields.io/badge/docker-ready-blue)](Dockerfile)
[![Azure: Container Apps + Bicep](https://img.shields.io/badge/azure-container%20apps%20%2B%20bicep-0078D4)](infra/azure/main.bicep)

Invoices and finance policy documents in; structured data, cited answers, and human-review routing out.
One shaped model call per question, deterministic everything else, refusal when evidence is insufficient.

## Use cases

| # | Use case | How LedgerLens handles it |
|---|---|---|
| 1 | **AP invoice triage** | Upload a PDF or scan → typed extraction (number, vendor, dates, totals, PO, line items) with required-field flags |
| 2 | **Policy compliance check** | Deterministic rules verify totals match, tax rate within cap, amount under approval threshold, PO present |
| 3 | **Auditor Q&A with evidence** | Ask in natural language → TF-IDF retrieval → answer stitched to cited source passages, or an explicit refusal |
| 4 | **Exception handling** | Any failed rule routes the document to a human review queue; approve/reject requires reviewer authorisation |
| 5 | **Regulated rollout evidence** | Versioned eval set + JSONL logs give latency, cost, and accuracy traces for sign-off |

## Architecture

```mermaid
flowchart LR
    UP[PDF / scan / TXT] --> GATE[Access checks<br/>X-API-Key + role]
    GATE --> OCR[OCR + text layer<br/>pypdf, tesseract fallback]
    OCR --> CLS[classify + extract<br/>typed Invoice / Policy JSON]
    CLS --> RULES[Business rules<br/>totals, tax, threshold, PO]
    RULES -->|fail| REVIEW[Human review queue<br/>reviewer-gated resolve]
    RULES -->|pass| INDEX[Passage index<br/>chunk + TF-IDF]
    OCR --> INDEX
    INDEX --> QA{Grounded QA<br/>single model call}
    QA -->|score >= 0.12| ANS[Answer + citations]
    QA -->|below threshold| REF[Refusal]
```

| Component | File | Role |
|---|---|---|
| API + UI | `app/main.py`, `templates/`, `static/` | Ingest, ask, reviews, metrics endpoints and workbench UI |
| OCR | `app/ocr.py` | pypdf text layer, tesseract fallback for scans, access-checked uploads |
| Extraction | `app/extract.py`, `app/schemas.py` | Regex extraction into Pydantic schemas + required-field checks |
| Rules | `app/rules.py` | Deterministic totals / tax / threshold / PO validation |
| Retrieval | `app/index.py` | Chunking + TF-IDF cosine retrieval with scored citations |
| Model call | `app/llm.py` | Single grounded call via the **local opencode service** (`opencode/muse-spark-1.3-contributor-free`); extractive fallback if unreachable. No API keys, no cloud endpoints. |
| Ops | `app/store.py`, `app/auth.py` | JSONL logs, latency/cost metrics, API-key + reviewer-role auth |
| Eval | `app/eval.py`, `tests/testset.v1.json` | Versioned test set (extraction, rules, groundedness, refusal, auth) |

## Quickstart

```
pip install -r requirements.txt
uvicorn app.main:app --port 8000   # UI at http://localhost:8000
```

### Docker

```
docker build -t ledgerlens:1.1.0 .
docker run -p 8000:8000 -e FIN_API_KEY=<secret> -e FIN_REVIEWER_KEY=<secret> ledgerlens:1.1.0
# or: docker compose up --build
```

Non-root user, pinned dependencies, `/health` + `/ready` probes, data on a volume.

### Azure

`infra/azure/main.bicep` deploys Container Apps (1–5 replicas, HTTP autoscale)
with secrets in Key Vault (managed identity, RBAC), Log Analytics, and
liveness/readiness probes:

```
az group create -n ledgerlens-rg -l westeurope
az deployment group create -g ledgerlens-rg --template-file infra/azure/main.bicep \
  --parameters image=<registry>/ledgerlens:1.1.0 apiKey=<secret> reviewerKey=<secret>
```

## Security

| Control | Implementation |
|---|---|
| Auth | `X-API-Key` header, constant-time compare, rotating keys via `FIN_API_KEYS` / `FIN_REVIEWER_KEYS`; reviewer role required for review resolution |
| Transport | TLS enforced at ingress (`allowInsecure: false` in Bicep); security headers (nosniff, DENY framing, no-referrer, CSP) |
| Abuse | 60 req/min per client (`RATE_LIMIT_PER_MIN`), 15 MB upload cap (`MAX_UPLOAD_BYTES`), filename sanitisation, restricted extensions |
| Secrets | Env-only, never logged; on Azure served from Key Vault via managed identity |
| Audit | Append-only `audit.jsonl` for ingests, review decisions, auth denials (contents and keys excluded) |
| Probes | `/health` (liveness) and `/ready` (store + upload writability) for orchestrators |

Demo keys: `X-API-Key: demo-key-123` (analyst). Reviewer actions need
`X-API-Key: reviewer-key-456` + `X-Role: reviewer`.
The single grounded-answer call goes through the local opencode background service
(`opencode run --model opencode/muse-spark-1.3-contributor-free`); no API keys are
used or accepted. If the service is unreachable, the offline extractive fallback
answers from retrieved passages (fully reproducible).

## Testing

```
python3 -m app.eval          # versioned eval over tests/testset.v1.json
python3 scripts/bench.py     # serving latency benchmark (see DEPLOYMENT.md)
```

The v1 set has 12 cases across 5 categories: extraction (3), business rules (3),
grounded QA (2), refusal of unanswerable questions (2), authorisation (2).
Eval writes its report to `data/store/eval_last.json`.

### Measured results (2026-10-15, 3 reproducible runs, n=12)

| Metric | Target | Result |
|---|---|---|
| Required-field extraction accuracy | ≥95% | 100% (3/3) |
| Answers with valid source evidence | ≥95% | 100% (2/2 answerable) |
| Correct refusal of unanswerable | ≥90% | 100% (2/2) |
| Test cases with recorded outcomes | 100% | 100% (12/12) |
| Critical tool actions w/o authorisation | 0 | 0 (analyst resolve → 403, verified live) |
| Reproducible evaluation runs | 3 | 3 × 12/12 |

Sample size is 12 and the fixtures are synthetic — these numbers validate the
pipeline, they are **not** a claim of production readiness. Failure categories found
during development (money-group indexing, `Tax (8%)` gap characters, `NoPO`
false-positive) were fixed and are kept as regression cases (E1/E3/R1/R3).
Managed-API vs self-hosted guidance and the measured CPU benchmark live in
[DEPLOYMENT.md](DEPLOYMENT.md).

## Contributing

Issues and PRs welcome. Please keep new extraction rules deterministic and covered
by a case in `tests/testset.v1.json` (bump to `v2` for schema changes), and keep the
model-call surface to the single shaped call in `app/llm.py`.

## License

[MIT](LICENSE)
