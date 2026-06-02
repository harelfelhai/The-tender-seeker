"""SmartTender AI — FastAPI application.

Process-once architecture:
  POST /tenders/ingest  →  extract (LLM, $1–3) + store analysis JSON
  GET  /match/{company}/{tender}  →  deterministic match on stored JSON (free)

Every tender is extracted ONCE regardless of how many companies query it.
Authentication: X-API-Key header (SHA-256 hashed at rest, shown plaintext once).
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from ..agents.criteria_agent import CriteriaAgent, resolve_model
from ..agents.graph import PipelineState, TenderPipeline
from ..match_engine.engine import evaluate_match
from ..match_engine.relevance import score_relevance
from ..schemas.company_profile import CompanyProfile
from ..schemas.tender import TenderAnalysisOutput
from .auth import generate_key, hash_key, require_auth, require_company_access
from .onboarding import router as onboarding_router
from .database import ApiKeyRow, CompanyRow, MatchResultRow, NotificationRow, RawTenderRow, TenderRow, get_db, init_db
from ..harvest.base import TenderStatus
from ..harvest.service import HarvestService
from ..harvest.sources.budgetkey import BudgetKeySource
from ..harvest.sources.manual import ManualSource
from ..harvest.sources.muni import MuniTendersSource
from ..notifications import ConsoleNotifier, EmailNotifier
from ..notifications.dispatcher import NotificationDispatcher
from ..scheduler import build_scheduler


# ── lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Build notifiers: always log to console; email when SMTP_HOST is set
    notifiers = [ConsoleNotifier()]
    if os.getenv("SMTP_HOST"):
        notifiers.append(EmailNotifier())
    dispatcher = NotificationDispatcher(notifiers)

    async def harvest_job() -> None:
        """Run all sources, then notify companies about new matching tenders."""
        from .database import SessionLocal, RawTenderRow
        svc = HarvestService(sources=[BudgetKeySource()])
        db = SessionLocal()
        try:
            results = await svc.run_all(db)
            # Notify for every tender that just moved to PENDING_ANALYSIS
            pending = (
                db.query(RawTenderRow)
                .filter(RawTenderRow.status == TenderStatus.PENDING_ANALYSIS.value)
                .all()
            )
            for row in pending:
                await dispatcher.dispatch_for_tender(row, db)
        finally:
            db.close()

    scheduler = build_scheduler(harvest_job)
    if scheduler:
        scheduler.start()

    yield

    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="SmartTender AI",
    description=(
        "Hebrew RAG pipeline: extract tender criteria once, match against many companies.\n\n"
        "**Authentication**: pass your API key in the `X-API-Key` header."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — origins controlled by ALLOWED_ORIGINS env var (comma-separated).
# Defaults to "*" for local dev; set a restrictive list in production.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
app.include_router(onboarding_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_raw_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── health ─────────────────────────────────────────────────────────────────────

@app.get("/health", summary="בדיקת תקינות", tags=["system"], include_in_schema=True)
def health():
    """Returns 200 OK when the service is up. No authentication required."""
    return {"status": "ok", "version": app.version}


# ══════════════════════════════════════════════════════════════════════════════
# /auth
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/auth/register", summary="רשום חברה וקבל API key", tags=["auth"])
def register(profile: CompanyProfile, db: Session = Depends(get_db)):
    """Create a company profile and issue an API key.

    **The plaintext key is returned ONCE — store it securely.**
    Subsequent requests must include `X-API-Key: <key>` in the header.
    """
    company_id = profile.company_reg_id or str(uuid.uuid4())

    # Upsert company
    co_row = db.get(CompanyRow, company_id) or CompanyRow(id=company_id)
    co_row.name = profile.company_name
    co_row.profile_json = profile.model_dump_json()
    db.add(co_row)

    # Generate key (stored as hash only)
    plaintext = generate_key()
    key_row = ApiKeyRow(
        key_hash=hash_key(plaintext),
        company_id=company_id,
        label=f"key for {profile.company_name}",
    )
    db.add(key_row)
    db.commit()

    return {
        "company_id": company_id,
        "api_key": plaintext,
        "warning": "שמור את המפתח — הוא מוצג פעם אחת בלבד ולא נשמר בשרת",
    }


@app.get("/auth/me", summary="מי אני?", tags=["auth"])
def me(auth: ApiKeyRow = Depends(require_auth), db: Session = Depends(get_db)):
    co = db.get(CompanyRow, auth.company_id)
    return {
        "company_id": auth.company_id,
        "company_name": co.name if co else None,
        "key_label": auth.label,
        "created_at": auth.created_at,
    }


@app.delete("/auth/revoke", summary="בטל את ה-API key הנוכחי", tags=["auth"])
def revoke(auth: ApiKeyRow = Depends(require_auth), db: Session = Depends(get_db)):
    auth.is_active = False
    db.commit()
    return {"message": "API key בוטל"}


# ══════════════════════════════════════════════════════════════════════════════
# /tenders  — shared (any authenticated company can read/ingest)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/tenders/ingest", summary="העלה PDF — חלץ פעם אחת, שמור לנצח", tags=["tenders"])
async def ingest_tender(
    file: UploadFile = File(..., description="קובץ PDF של המכרז"),
    model: str = Form(default="sonnet", description="haiku / sonnet / opus"),
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Upload a tender PDF. Extraction runs ONCE and the result is stored.
    Any subsequent match request uses the stored JSON — no re-extraction, no extra cost.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "יש להעלות קובץ PDF בלבד")

    model_id = resolve_model(model)

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
        "message": f"מכרז נשמר — לא יחולץ שוב. השתמש ב-/match/{auth.company_id}/{analysis.tender_id}",
    }


@app.get("/tenders", summary="רשימת כל המכרזים שחולצו", tags=["tenders"])
def list_tenders(
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
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


@app.get("/tenders/{tender_id}", summary="פרטי מכרז + קריטריונים שחולצו", tags=["tenders"])
def get_tender(
    tender_id: str,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    row = _get_or_404(db, TenderRow, tender_id, "מכרז")
    return json.loads(row.analysis_json)


# ══════════════════════════════════════════════════════════════════════════════
# /companies  — each company sees only its own data
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/companies/me", summary="פרופיל החברה שלי", tags=["companies"])
def get_my_company(
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    row = _get_or_404(db, CompanyRow, auth.company_id, "חברה")
    return json.loads(row.profile_json)


@app.put("/companies/me", summary="עדכן פרופיל החברה שלי", tags=["companies"])
def update_my_company(
    profile: CompanyProfile,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    row = _get_or_404(db, CompanyRow, auth.company_id, "חברה")
    row.name = profile.company_name
    row.profile_json = profile.model_dump_json()
    db.commit()
    return {"company_id": auth.company_id, "name": profile.company_name, "updated": True}


# ══════════════════════════════════════════════════════════════════════════════
# /match  — deterministic, no LLM, free; scoped to authenticated company
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/match/{tender_id}", summary="בדוק כשירות ורלוונטיות למכרז (ללא LLM)", tags=["match"])
def match(
    tender_id: str,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Run the deterministic Match Engine against the stored tender JSON.
    No LLM call, no cost — uses the company profile from the authenticated key.
    """
    tender_row = _get_or_404(db, TenderRow, tender_id, "מכרז")
    company_row = _get_or_404(db, CompanyRow, auth.company_id, "חברה")

    company = CompanyProfile.model_validate_json(company_row.profile_json)
    analysis = TenderAnalysisOutput.model_validate_json(tender_row.analysis_json)

    match_report = evaluate_match(company, analysis)
    relevance = score_relevance(company, analysis.tender_profile)
    final_score = 0.0 if not match_report.is_eligible else relevance.relevance_score

    result_id = f"{auth.company_id}__{tender_id}"
    db.merge(MatchResultRow(
        id=result_id,
        company_id=auth.company_id,
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
    ))
    db.commit()

    return {
        "company_id": auth.company_id,
        "tender_id": tender_id,
        "is_eligible": match_report.is_eligible,
        "compatibility_score": match_report.compatibility_score,
        "relevance_score": relevance.relevance_score,
        "final_score": final_score,
        "summary_he": match_report.summary_he,
        "breakdown": [r.model_dump() for r in match_report.breakdown],
        "relevance_factors": [f.model_dump() for f in relevance.factors],
    }


@app.get("/match", summary="כל המכרזים מדורגים עבור החברה שלי", tags=["match"])
def my_matches(
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Match authenticated company against ALL stored tenders. Returns ranked list.
    Pure Python — no LLM, no cost per company.
    """
    company_row = _get_or_404(db, CompanyRow, auth.company_id, "חברה")
    company = CompanyProfile.model_validate_json(company_row.profile_json)

    tenders = db.query(TenderRow).all()
    if not tenders:
        return {"company_id": auth.company_id, "matches": []}

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
    return {"company_id": auth.company_id, "total": len(results), "matches": results}


# ══════════════════════════════════════════════════════════════════════════════
# /harvest  — source management and manual run trigger
# ══════════════════════════════════════════════════════════════════════════════

def _harvest_service() -> HarvestService:
    return HarvestService(sources=[BudgetKeySource(), MuniTendersSource(), ManualSource()])


@app.get("/notifications", summary="היסטוריית התראות של החברה שלי", tags=["harvest"])
def my_notifications(
    limit: int = 20,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(NotificationRow)
        .filter(NotificationRow.company_id == auth.company_id)
        .order_by(NotificationRow.sent_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "raw_tender_id": r.raw_tender_id,
            "channel": r.channel,
            "status": r.status,
            "sent_at": r.sent_at,
            "error_msg": r.error_msg,
        }
        for r in rows
    ]


@app.get("/harvest/sources", summary="מקורות קצירה זמינים", tags=["harvest"])
def list_harvest_sources(auth: ApiKeyRow = Depends(require_auth)):
    svc = _harvest_service()
    return {"sources": svc.list_sources()}


@app.post("/harvest/run", summary="הפעל קצירה ידנית ממקור נבחר", tags=["harvest"])
async def run_harvest(
    source_id: str = "budgetkey",
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Fetch new tenders from the given source, apply the metadata filter,
    and persist them to raw_tenders.  Does NOT run LLM extraction.
    """
    svc = _harvest_service()
    try:
        result = await svc.run_source(source_id, db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "source_id": result.source_id,
        "fetched": result.fetched,
        "new": result.new,
        "duplicates": result.duplicates,
        "pending_analysis": result.pending_analysis,
        "rejected": result.rejected,
        "errors": result.errors,
    }


@app.post("/harvest/re-evaluate", summary="הפעל סינון מחדש על מכרזים שנדחו", tags=["harvest"])
def re_evaluate_rejected(
    limit: int = 2000,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Re-run the current metadata filter on all REJECTED tenders.

    Use after improving taxonomy.py or updating the company profile —
    tenders that were previously rejected may now pass the improved filter.
    Returns counts of tenders promoted to PENDING_ANALYSIS.
    """
    from ..harvest.filter import BasicMetadataFilter
    from ..harvest.base import RawTenderRecord, TenderStatus as TS

    company_row = db.query(CompanyRow).filter_by(id=auth.company_id).first()
    if not company_row:
        raise HTTPException(404, "פרופיל חברה לא נמצא")
    company = CompanyProfile.model_validate_json(company_row.profile_json)
    flt = BasicMetadataFilter()

    rejected_rows = (
        db.query(RawTenderRow)
        .filter(RawTenderRow.status == TenderStatus.REJECTED.value)
        .limit(limit)
        .all()
    )

    promoted = 0
    for row in rejected_rows:
        rec = RawTenderRecord(
            source_id=row.source_id,
            external_id=row.external_id,
            title_he=row.title_he or "",
            publisher_he=row.publisher_he,
            subjects=json.loads(row.subjects_json or "[]"),
            tender_type=row.tender_type,
            publication_date=None,
            deadline=None,
            estimated_budget_ils=row.estimated_budget_ils,
            pdf_urls=json.loads(row.pdf_urls_json or "[]"),
            page_url=row.page_url,
            publisher_unit=row.publisher_unit,
        )
        if flt.should_analyze(rec, [company]):
            row.status = TenderStatus.PENDING_ANALYSIS.value
            promoted += 1

    db.commit()
    return {
        "evaluated": len(rejected_rows),
        "promoted_to_pending": promoted,
        "still_rejected": len(rejected_rows) - promoted,
    }


# ══════════════════════════════════════════════════════════════════════════════
# /raw-tenders  — inspect and trigger analysis of harvested records
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/raw-tenders", summary="מכרזים שנקצרו (לפני ניתוח LLM)", tags=["harvest"])
def list_raw_tenders(
    status: str | None = None,
    source_id: str | None = None,
    limit: int = 50,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    q = db.query(RawTenderRow)
    if status:
        q = q.filter(RawTenderRow.status == status)
    if source_id:
        q = q.filter(RawTenderRow.source_id == source_id)
    rows = q.order_by(RawTenderRow.harvested_at.desc()).limit(limit).all()
    return [_raw_tender_summary(r) for r in rows]


@app.get("/raw-tenders/{raw_id}", summary="פרטי רשומת raw tender", tags=["harvest"])
def get_raw_tender(
    raw_id: str,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    row = _get_or_404(db, RawTenderRow, raw_id, "raw tender")
    d = _raw_tender_summary(row)
    d["raw_metadata"] = json.loads(row.raw_metadata_json or "{}")
    return d


@app.post("/raw-tenders/{raw_id}/analyze", summary="הפעל ניתוח LLM על raw tender", tags=["harvest"])
async def analyze_raw_tender(
    raw_id: str,
    model: str = "sonnet",
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Trigger LLM extraction for a single raw tender that has a PDF URL or blob.
    Only tenders in PENDING_ANALYSIS or REJECTED status can be re-analyzed.
    """
    row = _get_or_404(db, RawTenderRow, raw_id, "raw tender")
    if row.status == TenderStatus.ANALYZED.value:
        raise HTTPException(400, "מכרז זה כבר נותח")

    pdf_urls = json.loads(row.pdf_urls_json or "[]")
    if not pdf_urls and not row.pdf_blob:
        raise HTTPException(400, "אין קובץ PDF זמין לניתוח")

    model_id = resolve_model(model)

    # Download PDF from first available URL (or use stored blob)
    import base64
    if row.pdf_blob:
        pdf_bytes = base64.b64decode(row.pdf_blob)
    else:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(pdf_urls[0])
                resp.raise_for_status()
                pdf_bytes = resp.content
        except Exception as exc:
            raise HTTPException(502, f"לא ניתן להוריד את ה-PDF: {exc}")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
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

    from datetime import datetime, timezone
    tender_row = db.get(TenderRow, analysis.tender_id) or TenderRow(id=analysis.tender_id)
    tender_row.title_he = analysis.title_he
    tender_row.publisher_he = analysis.publisher_he
    tender_row.source_pdf = pdf_urls[0] if pdf_urls else "manual"
    tender_row.analysis_json = analysis.model_dump_json()
    tender_row.model_used = model_id
    db.add(tender_row)

    row.status = TenderStatus.ANALYZED.value
    row.analysis_id = analysis.tender_id
    row.analyzed_at = datetime.now(timezone.utc).isoformat()
    db.commit()

    return {
        "raw_tender_id": raw_id,
        "tender_id": analysis.tender_id,
        "title_he": analysis.title_he,
        "criteria_count": len(analysis.criteria),
        "model_used": model_id,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _raw_tender_summary(r: RawTenderRow) -> dict:
    return {
        "id": r.id,
        "source_id": r.source_id,
        "external_id": r.external_id,
        "title_he": r.title_he,
        "publisher_he": r.publisher_he,
        "publisher_unit": r.publisher_unit,
        "subjects": json.loads(r.subjects_json or "[]"),
        "tender_type": r.tender_type,
        "tender_type_he": r.tender_type_he,
        "publication_date": r.publication_date.isoformat() if r.publication_date else None,
        "deadline": r.deadline.isoformat() if r.deadline else None,
        "contract_start": r.contract_start.isoformat() if r.contract_start else None,
        "contract_end": r.contract_end.isoformat() if r.contract_end else None,
        "estimated_budget_ils": r.estimated_budget_ils,
        "pdf_urls": json.loads(r.pdf_urls_json or "[]"),
        "page_url": r.page_url,
        "tender_status": r.tender_status,
        "decision": r.decision,
        "status": r.status,
        "analysis_id": r.analysis_id,
        "uploaded_by": r.uploaded_by,
        "harvested_at": r.harvested_at,
        "analyzed_at": r.analyzed_at,
    }


def _get_or_404(db: Session, model, pk: str, label: str):
    row = db.get(model, pk)
    if row is None:
        raise HTTPException(404, f"{label} '{pk}' לא נמצא")
    return row


def _dummy_company() -> CompanyProfile:
    """Minimal profile needed to initialize PipelineState during ingestion."""
    return CompanyProfile(
        company_name="__ingest__",
        company_reg_id="000000000",
        annual_revenues={},
    )
