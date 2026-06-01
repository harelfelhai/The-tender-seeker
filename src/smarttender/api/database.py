"""SQLite persistence layer.

Process-once architecture: tenders are extracted (expensive LLM) and stored as JSON.
Match Engine runs on-demand against the stored JSON — no re-extraction per user.

Using SQLite for dev/PoC; swappable to PostgreSQL by changing DATABASE_URL.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, Float, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./smarttender.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


class TenderRow(Base):
    __tablename__ = "tenders"

    id = Column(String, primary_key=True)          # tender_id from extraction
    title_he = Column(String, nullable=False)
    publisher_he = Column(String, nullable=True)
    source_pdf = Column(String, nullable=True)      # original filename
    analysis_json = Column(Text, nullable=False)    # full TenderAnalysisOutput JSON
    model_used = Column(String, nullable=True)
    created_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())


class CompanyRow(Base):
    __tablename__ = "companies"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    profile_json = Column(Text, nullable=False)     # full CompanyProfile JSON
    created_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    key_hash = Column(String, primary_key=True)     # SHA-256 of plaintext key
    company_id = Column(String, nullable=False, index=True)
    label = Column(String, nullable=True)           # human-readable note
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())


class MatchResultRow(Base):
    __tablename__ = "match_results"

    id = Column(String, primary_key=True)           # "{company_id}__{tender_id}"
    company_id = Column(String, nullable=False, index=True)
    tender_id = Column(String, nullable=False, index=True)
    is_eligible = Column(Boolean, nullable=False)
    compatibility_score = Column(Float, nullable=False)
    relevance_score = Column(Float, nullable=True)
    final_score = Column(Float, nullable=True)
    report_json = Column(Text, nullable=False)      # full MatchReport + RelevanceReport JSON
    computed_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())


class RawTenderRow(Base):
    """A tender record as received from a harvest source — before LLM analysis.

    Lifecycle: DISCOVERED → PENDING_FILTER → PENDING_ANALYSIS → ANALYZED
                                            ↘ REJECTED
    Manual uploads enter at PENDING_ANALYSIS and are processed immediately.
    """

    __tablename__ = "raw_tenders"

    id = Column(String, primary_key=True)       # internal UUID
    source_id = Column(String, nullable=False, index=True)   # "budgetkey" | "manual" | ...
    external_id = Column(String, nullable=True, index=True)  # ID in source system (dedup key)
    title_he = Column(String, nullable=True)
    publisher_he = Column(String, nullable=True)
    subjects_json = Column(Text, nullable=True)             # JSON list of subject strings
    tender_type = Column(String, nullable=True)             # "office"|"central"|"exemptions"
    publication_date = Column(Date, nullable=True)
    deadline = Column(Date, nullable=True)                  # submission deadline
    estimated_budget_ils = Column(Float, nullable=True)
    pdf_urls_json = Column(Text, nullable=True)             # JSON list of URL strings
    pdf_blob = Column(Text, nullable=True)                  # base64 for manual uploads
    uploaded_by = Column(String, nullable=True, index=True) # company_id (manual uploads)
    status = Column(String, nullable=False, default="discovered", index=True)
    analysis_id = Column(String, nullable=True)             # FK → tenders.id after analysis
    raw_metadata_json = Column(Text, nullable=True)         # full API response
    harvested_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    analyzed_at = Column(String, nullable=True)


def init_db() -> None:
    """Run Alembic migrations to head (idempotent, safe on existing DBs)."""
    from alembic import command
    from alembic.config import Config

    ini_path = _find_alembic_ini()
    if ini_path is None:
        # Fallback for environments where alembic.ini is not present (e.g. tests)
        Base.metadata.create_all(bind=engine)
        return

    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")


def _find_alembic_ini() -> "str | None":
    """Locate alembic.ini by searching from the package root upward."""
    import pathlib

    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "alembic.ini"
        if candidate.exists():
            return str(candidate)
    return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
