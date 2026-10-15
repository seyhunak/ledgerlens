"""Enterprise security: request IDs, security headers, rate limiting, audit log."""
from __future__ import annotations
import hmac
import os
import time
import uuid
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app import store

RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
_hits: dict[str, list[float]] = defaultdict(list)


def api_keys() -> list[str]:
    raw = os.getenv("FIN_API_KEYS", "")  # comma-separated, supports rotation
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    keys += [os.getenv("FIN_API_KEY", "demo-key-123"),
             os.getenv("FIN_REVIEWER_KEY", "reviewer-key-456")]
    return keys


def reviewer_keys() -> list[str]:
    raw = os.getenv("FIN_REVIEWER_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    keys.append(os.getenv("FIN_REVIEWER_KEY", "reviewer-key-456"))
    return keys


def key_matches(presented: str | None, candidates: list[str]) -> bool:
    if not presented:
        return False
    return any(hmac.compare_digest(presented, c) for c in candidates)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' fonts.googleapis.com; "
            "font-src fonts.gstatic.com; script-src 'self' 'unsafe-inline'")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in ("/health", "/ready"):
            return await call_next(request)
        ident = request.headers.get("X-API-Key", "") + "|" + (request.client.host if request.client else "?")
        now = time.time()
        window = [t for t in _hits[ident] if now - t < 60]
        _hits[ident] = window
        if len(window) >= RATE_LIMIT_PER_MIN:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": "60"})
        window.append(now)
        return await call_next(request)


def audit(event: str, **fields) -> None:
    """Append-only audit trail. Never logs file contents or secrets."""
    safe = {k: v for k, v in fields.items() if "key" not in k.lower() and "secret" not in k.lower()}
    store._append(store.STORE / "audit.jsonl", {"event": event, **safe})
