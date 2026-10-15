"""Serving benchmark: ingest + retrieve + answer latency."""
import sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.samples import SAMPLE_INVOICE
from app.extract import extract_invoice
from app.index import chunk, retrieve
from app.llm import grounded_answer
from app.rules import run_rules

def bench(n=20):
    corpus = chunk(SAMPLE_INVOICE * 5, "bench")
    lat = {"extract": [], "retrieve": [], "answer": []}
    for _ in range(n):
        t = time.time(); extract_invoice(SAMPLE_INVOICE); run_rules(extract_invoice(SAMPLE_INVOICE))
        lat["extract"].append((time.time()-t)*1000)
        t = time.time(); c = retrieve("grand total INV-2026-0481", corpus)
        lat["retrieve"].append((time.time()-t)*1000)
        t = time.time(); grounded_answer("grand total?", c)
        lat["answer"].append((time.time()-t)*1000)
    for k, v in lat.items():
        print(f"{k}: mean {statistics.mean(v):.1f} ms, p95 {sorted(v)[int(0.95*(n-1))]:.1f} ms")

if __name__ == "__main__":
    bench()
