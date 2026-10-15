"""TF-IDF retrieval over chunked passages with citations + refusal."""
from __future__ import annotations
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.schemas import Citation

MIN_SCORE = 0.12  # below this -> refuse (insufficient evidence)
TOP_K = 3


def chunk(text: str, doc_id: str, size: int = 600, overlap: int = 120) -> list[dict]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    passages: list[dict] = []
    for i, p in enumerate(paras):
        if len(p) <= size:
            passages.append({"doc_id": doc_id, "page": 1, "passage": p})
        else:
            for s in range(0, len(p), size - overlap):
                passages.append({"doc_id": doc_id, "page": 1, "passage": p[s:s + size]})
    return passages or [{"doc_id": doc_id, "page": 1, "passage": text[:size]}]


def retrieve(query: str, corpus: list[dict], top_k: int = TOP_K) -> list[Citation]:
    if not corpus:
        return []
    docs = [c["passage"] for c in corpus]
    vec = TfidfVectorizer(stop_words="english").fit(docs + [query])
    m = vec.transform(docs)
    q = vec.transform([query])
    scores = cosine_similarity(q, m)[0]
    ranked = sorted(zip(corpus, scores), key=lambda x: -x[1])[:top_k]
    return [Citation(doc_id=c["doc_id"], page=c.get("page", 1),
                     passage=c["passage"][:500], score=float(s)) for c, s in ranked]
