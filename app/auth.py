"""Access control: rotating API keys (constant-time compare) + roles.

Keys come from env only — never hardcoded for production:
  FIN_API_KEYS       comma-separated active keys (rotation: old+new overlap)
  FIN_REVIEWER_KEYS  comma-separated reviewer keys
Dev defaults apply only when env is unset.
"""
from __future__ import annotations
import os
from fastapi import Header, HTTPException
from app.security import api_keys, reviewer_keys, key_matches, audit


def check_access(x_api_key: str | None = Header(default=None),
                 x_role: str | None = Header(default="analyst")) -> str:
    if not key_matches(x_api_key, api_keys()):
        audit("auth.denied", reason="bad_api_key")
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return (x_role or "analyst").lower()


def require_reviewer(role: str, x_api_key: str | None = None) -> None:
    if key_matches(x_api_key, reviewer_keys()) or role in ("reviewer", "admin"):
        return
    audit("auth.denied", reason="reviewer_required", role=role)
    raise HTTPException(status_code=403, detail="Reviewer authorisation required for this action")
