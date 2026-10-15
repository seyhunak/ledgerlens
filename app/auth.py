"""Simple access control: API key + roles. Demo defaults, override via env."""
from __future__ import annotations
import os
from fastapi import Header, HTTPException

API_KEY = os.getenv("FIN_API_KEY", "demo-key-123")
REVIEWER_KEY = os.getenv("FIN_REVIEWER_KEY", "reviewer-key-456")


def check_access(x_api_key: str | None = Header(default=None),
                 x_role: str | None = Header(default="analyst")) -> str:
    if x_api_key not in (API_KEY, REVIEWER_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return (x_role or "analyst").lower()


def require_reviewer(role: str, x_api_key: str | None = None) -> None:
    if x_api_key == REVIEWER_KEY or role in ("reviewer", "admin"):
        return
    raise HTTPException(status_code=403, detail="Reviewer authorisation required for this action")
