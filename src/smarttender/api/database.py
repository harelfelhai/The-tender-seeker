"""SQLite persistence layer.

Process-once architecture: tenders are extracted (expensive LLM) and stored as JSON.
Match Engine runs on-demand against the stored JSON — no re-extraction per user.

Using SQLite for dev/PoC; swappable to PostgreSQL by changing DATABASE_URL.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Float, String, Text, create_engine, text
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


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
