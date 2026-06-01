"""SmartTender AI — FastAPI application.

Process-once architecture:
  POST /tenders/ingest  →  extract (LLM, $1–3) + store analysis JSON
  GET  /match/{company}/{tender}  →  deterministic match on stored JSON (free)

Every tender is extracted ONCE regardless of how many companies query it.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..agents.criteria_agent import CriteriaAgent, resolve_model
from ..agents.graph import PipelineState, TenderPipeline
from ..match_engine.engine import evaluate_match
from ..match_engine.relevance import score_relevance
from ..schemas.company_profile import CompanyProfile
from ..schemas.tender import TenderAnalysisOutput
from .database import CompanyRow, MatchResultRow, TenderRow, get_db, init_db


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SmartTender AI",
    description="Hebrew RAG pipeline: extract tender criteria once, match against many companies.",
    version="0.1.0",
    lifespan=lifespan,
)


# ══════════════════════════════════════════════════════════════════════════════
# /tenders
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/tenders/ingest", summary="העלה PDF — חלץ פעם אחת, שמור לנצח")
async def ingest_tender(
    file: UploadFile = File(..., description="קובץ PDF של המכרז"),
    model: str = Form(default="sonnet", description="haiku / sonnet / opus"),
    db: Session = Depends(get_db),
):
    """Upload a tender PDF. Extraction runs ONCE and is stored.
    Subsequent match requests use the stored JSON — no re-extraction, no extra cost.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "יש להעלות קובץ PDF בלבד")

    model_id = resolve_model(model)

    # Write to temp file (LLM pipeline expects a path)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        agent = CriteriaAgent(model=model_id)
        pipeline = TenderPipeline(criteria_agent=agent)
        state = pipeline.node_extract_criteria(
            PipelineState(company=_dummy_company(), pdf_path=tmp_path)
        )
        analysis: TenderAnalysisOutput = state.analysis
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Upsert: re-ingesting the same tender_id overwrites (idempotent)
    row = db.get(TenderRow, analysis.tender_id) or TenderRow(id=analysis.tender_id)
    row.title_he = analysis.title_he
    row.publisher_he = analysis.publisher_he
    row.source_pdf = file.filename
    row.analysis_json = analysis.model_dump_json()
    row.model_used = model_id
    db.add(row)
    db.commit()

    return {
        "tender_id": analysis.tender_id,
        "title_he": analysis.title_he,
        "publisher_he": analysis.publisher_he,
        "criteria_count": len(analysis.criteria),
        "model_used": model_id,
        "message": f"מכרז נשמר — לא יחולץ שוב. השתמש ב-/match/{{company_id}}/{analysis.tender_id}",
    }


@app.get("/tenders", summary="רשימת כל המכרזים שחולצו")
def list_tenders(db: Session = Depends(get_db)):
    rows = db.query(TenderRow).order_by(TenderRow.created_at.desc()).all()
    return [
        {
            "tender_id": r.id,
            "title_he": r.title_he,
            "publisher_he": r.publisher_he,
            "source_pdf": r.source_pdf,
            "model_used": r.model_used,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@app.get("/tenders/{tender_id}", summary="פרטי מכרז + קריטריונים שחולצו")
def get_tender(tender_id: str, db: Session = Depends(get_db)):
    row = _get_or_404(db, TenderRow, tender_id, "מכרז")
    return json.loads(row.analysis_json)


# ══════════════════════════════════════════════════════════════════════════════
# /companies
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/companies", summary="הוסף חברה")
def create_company(profile: CompanyProfile, db: Session = Depends(get_db)):
    company_id = profile.company_reg_id or str(uuid.uuid4())
    row = db.get(CompanyRow, company_id) or CompanyRow(id=company_id)
    row.name = profile.company_name
    row.profile_json = profile.model_dump_json()
    db.add(row)
    db.commit()
    return {"company_id": company_id, "name": profile.company_name}


@app.get("/companies", summary="רשימת כל החברות")
def list_companies(db: Session = Depends(get_db)):
    rows = db.query(CompanyRow).order_by(CompanyRow.created_at.desc()).all()
    return [{"company_id": r.id, "name": r.name, "created_at": r.created_at} for r in rows]


@app.get("/companies/{company_id}", summary="פרופיל חברה")
def get_company(company_id: str, db: Session = Depends(get_db)):
    row = _get_or_404(db, CompanyRow, company_id, "חברה")
    return json.loads(row.profile_json)


# ══════════════════════════════════════════════════════════════════════════════
# /match  — deterministic, no LLM, free
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/match/{company_id}/{tender_id}", summary="בדוק כשירות ורלוונטיות (ללא LLM)")
def match(company_id: str, tender_id: str, db: Session = Depends(get_db)):
    """Run the deterministic Match Engine against stored JSON. No LLM, no cost."""
    company_row = _get_or_404(db, CompanyRow, company_id, "חברה")
    tender_row = _get_or_404(db, TenderRow, tender_id, "מכרז")

    company = CompanyProfile.model_validate_json(company_row.profile_json)
    analysis = TenderAnalysisOutput.model_validate_json(tender_row.analysis_json)

    match_report = evaluate_match(company, analysis)
    relevance = score_relevance(company, analysis.tender_profile)
    final_score = 0.0 if not match_report.is_eligible else relevance.relevance_score

    # Cache result
    result_id = f"{company_id}__{tender_id}"
    cached = MatchResultRow(
        id=result_id,
        company_id=company_id,
        tender_id=tender_id,
        is_eligible=match_report.is_eligible,
        compatibility_score=match_report.compatibility_score,
        relevance_score=relevance.relevance_score,
        final_score=final_score,
        report_json=json.dumps({
            "match": match_report.model_dump(),
            "relevance": relevance.model_dump(),
            "final_score": final_score,
        }, ensure_ascii=False),
    )
    db.merge(cached)
    db.commit()

    return {
        "company_id": company_id,
        "tender_id": tender_id,
        "is_eligible": match_report.is_eligible,
        "compatibility_score": match_report.compatibility_score,
        "relevance_score": relevance.relevance_score,
        "final_score": final_score,
        "summary_he": match_report.summary_he,
        "breakdown": [r.model_dump() for r in match_report.breakdown],
        "relevance_factors": [f.model_dump() for f in relevance.factors],
    }


@app.get("/companies/{company_id}/matches", summary="כל המכרזים מדורגים לפי ציון")
def company_matches(company_id: str, db: Session = Depends(get_db)):
    """Match a company against ALL stored tenders. Returns ranked list."""
    company_row = _get_or_404(db, CompanyRow, company_id, "חברה")
    company = CompanyProfile.model_validate_json(company_row.profile_json)

    tenders = db.query(TenderRow).all()
    if not tenders:
        return {"company_id": company_id, "matches": []}

    results = []
    for t in tenders:
        analysis = TenderAnalysisOutput.model_validate_json(t.analysis_json)
        match_report = evaluate_match(company, analysis)
        relevance = score_relevance(company, analysis.tender_profile)
        final = 0.0 if not match_report.is_eligible else relevance.relevance_score
        results.append({
            "tender_id": t.id,
            "title_he": t.title_he,
            "publisher_he": t.publisher_he,
            "is_eligible": match_report.is_eligible,
            "compatibility_score": match_report.compatibility_score,
            "relevance_score": relevance.relevance_score,
            "final_score": final,
            "summary_he": match_report.summary_he,
        })

    results.sort(key=lambda x: x["final_score"], reverse=True)
    return {"company_id": company_id, "total": len(results), "matches": results}


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, model, pk: str, label: str):
    row = db.get(model, pk)
    if row is None:
        raise HTTPException(404, f"{label} '{pk}' לא נמצא")
    return row


def _dummy_company() -> CompanyProfile:
    """Minimal profile needed to initialize PipelineState (not used in extraction)."""
    return CompanyProfile(
        company_name="__ingest__",
        company_reg_id="000000000",
        annual_revenues={},
    )
