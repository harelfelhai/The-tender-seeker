"""API key authentication.

Keys are stored as SHA-256 hashes only — plaintext is shown ONCE at registration
and never stored. Format: sk-st-{32 hex chars} (recognisable prefix, easy to audit
in logs/code without exposing the secret).
"""
from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from .database import ApiKeyRow, get_db

_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def generate_key() -> str:
    """Return a new plaintext API key. Called once at registration — never stored."""
    return f"sk-st-{secrets.token_hex(32)}"


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def require_auth(
    api_key: str | None = Security(_HEADER),
    db: Session = Depends(get_db),
) -> ApiKeyRow:
    """FastAPI dependency — validates X-API-Key and returns the ApiKeyRow.

    Raises 401 when key is missing or invalid, 403 when key is revoked.
    """
    if not api_key:
        raise HTTPException(401, "נדרש X-API-Key header")
    row = db.query(ApiKeyRow).filter_by(key_hash=hash_key(api_key)).first()
    if row is None:
        raise HTTPException(401, "API key לא תקין")
    if not row.is_active:
        raise HTTPException(403, "API key בוטל")
    return row


def require_company_access(company_id: str, auth: ApiKeyRow) -> None:
    """Raise 403 if the authenticated key does not belong to company_id."""
    if auth.company_id != company_id:
        raise HTTPException(403, "אין הרשאה לגשת לנתונים של חברה אחרת")
