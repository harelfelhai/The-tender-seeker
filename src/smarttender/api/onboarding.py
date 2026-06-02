"""Onboarding API — guided profile building in 3 steps.

Step 2: Conversational interview (3-4 questions, LLM extracts structured additions)
Step 3: Active learning — user reviews sample tenders, LLM proposes profile diff
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.criteria_agent import resolve_model
from .auth import require_auth
from .database import ApiKeyRow, CompanyRow, RawTenderRow, get_db
from ..harvest.base import TenderStatus
from ..schemas.company_profile import CompanyProfile

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

_LLM_MODEL = os.getenv("ONBOARDING_MODEL", "claude-haiku-4-5-20251001")

INTERVIEW_QUESTIONS = [
    "תאר בשתיים-שלוש משפטים את תחום הפעילות העיקרי של החברה שלך.",
    "איזה סוגי פרויקטים אתם מחפשים? (ממשלתי / עירוני / פרטי, תחזוקה / הקמה, גודל טיפוסי)",
    "תאר פרויקט שביצעתם לאחרונה שהיה מוצלח ומייצג את הפעילות שלכם.",
    "מה בהחלט לא מתאים לכם? ציין סוגי עבודה, תחומים, או לקוחות שאתם לא רוצים.",
]


# ── Schemas ───────────────────────────────────────────────────────────────────

class QAPair(BaseModel):
    question: str
    answer: str


class InterviewRequest(BaseModel):
    answers: list[QAPair]


class InterviewResponse(BaseModel):
    done: bool
    next_question: str | None = None
    question_index: int | None = None
    total_questions: int = len(INTERVIEW_QUESTIONS)
    suggestions: dict[str, Any] | None = None  # populated when done=True


class TenderFeedback(BaseModel):
    raw_tender_id: str
    title: str
    publisher: str | None = None
    subjects: list[str] = []
    budget_ils: float | None = None
    relevant: bool
    reason: str = ""


class FeedbackRequest(BaseModel):
    feedbacks: list[TenderFeedback]


class ProfileDiff(BaseModel):
    add_domains: list[str] = []
    remove_domains: list[str] = []
    add_keywords: list[str] = []
    remove_keywords: list[str] = []
    add_negative_patterns: list[str] = []
    add_regions: list[str] = []
    add_client_types: list[str] = []
    explanation_he: str = ""


class FeedbackResponse(BaseModel):
    diff: ProfileDiff
    summary_he: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _call_llm(prompt: str, system: str) -> str:
    client = _get_client()
    msg = client.messages.create(
        model=_LLM_MODEL,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _load_profile(db: Session, company_id: str) -> CompanyProfile:
    row = db.get(CompanyRow, company_id)
    return CompanyProfile.model_validate_json(row.profile_json) if row else CompanyProfile(
        company_name="", annual_revenues={}
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/interview", response_model=InterviewResponse)
def interview_step(
    body: InterviewRequest,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Stateless interview: send all answers so far, receive next question or final suggestions."""
    n = len(body.answers)

    if n < len(INTERVIEW_QUESTIONS):
        return InterviewResponse(
            done=False,
            next_question=INTERVIEW_QUESTIONS[n],
            question_index=n,
        )

    # All questions answered — extract structured profile additions
    profile = _load_profile(db, auth.company_id)

    qa_text = "\n".join(
        f"ש: {qa.question}\nת: {qa.answer}" for qa in body.answers
    )

    prompt = f"""פרופיל החברה הנוכחי:
- שם: {profile.company_name}
- תחומים: {', '.join(profile.domains) or 'לא הוגדר'}
- אזורים: {', '.join(profile.operating_regions) or 'לא הוגדר'}

תשובות המשתמש לשאלות:
{qa_text}

על בסיס התשובות, חלץ הצעות לעדכון הפרופיל. ענה ב-JSON בלבד:
{{
  "suggested_domains": ["תחום1", "תחום2"],
  "suggested_keywords": ["מילה1", "מילה2"],
  "suggested_regions": ["אזור1"],
  "suggested_client_types": ["government", "municipal", "private"],
  "suggested_negatives": ["דבר שלא רוצים1"],
  "summary_he": "סיכום קצר של מה שלמדנו"
}}

הערות:
- domains: תחומי עיסוק (מיזוג אויר, קירור, אוורור, חשמל, אינסטלציה...)
- keywords: מילות מפתח ספציפיות שיופיעו בכותרות מכרזים
- client_types: רק מתוך [government, municipal, private, ngo]
- suggested_negatives: תחומים/מילות מפתח שיגרמו לדחיית מכרז"""

    raw = _call_llm(prompt, "אתה עוזר לחברות קבלן לבנות פרופיל עבור מערכת מכרזים. ענה ב-JSON בלבד.")
    suggestions = json.loads(raw)

    return InterviewResponse(done=True, suggestions=suggestions)


@router.get("/samples")
def get_samples(
    limit: int = 15,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return a mix of tenders for the user to review (active learning step)."""
    pending = (
        db.query(RawTenderRow)
        .filter(RawTenderRow.status == TenderStatus.PENDING_ANALYSIS.value)
        .order_by(RawTenderRow.harvested_at.desc())
        .limit(limit)
        .all()
    )

    # If not enough pending, pad with rejected (for diversity)
    if len(pending) < limit:
        rejected = (
            db.query(RawTenderRow)
            .filter(RawTenderRow.status == TenderStatus.REJECTED.value)
            .order_by(RawTenderRow.harvested_at.desc())
            .limit(limit - len(pending))
            .all()
        )
        rows = pending + rejected
    else:
        rows = pending

    return [
        {
            "id": r.id,
            "title_he": r.title_he,
            "publisher_he": r.publisher_he,
            "subjects": json.loads(r.subjects_json or "[]"),
            "tender_type": r.tender_type,
            "estimated_budget_ils": r.estimated_budget_ils,
            "deadline": r.deadline.isoformat() if r.deadline else None,
            "filter_passed": r.status == TenderStatus.PENDING_ANALYSIS.value,
        }
        for r in rows
    ]


@router.post("/analyze-feedback", response_model=FeedbackResponse)
def analyze_feedback(
    body: FeedbackRequest,
    auth: ApiKeyRow = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Analyze user's tender feedback and propose a profile diff."""
    profile = _load_profile(db, auth.company_id)

    liked = [f for f in body.feedbacks if f.relevant]
    disliked = [f for f in body.feedbacks if not f.relevant]

    def _fmt(items: list[TenderFeedback]) -> str:
        return json.dumps(
            [{"title": f.title, "subjects": f.subjects, "reason": f.reason} for f in items],
            ensure_ascii=False,
            indent=2,
        )

    prompt = f"""פרופיל חברה נוכחי:
- תחומים: {', '.join(profile.domains) or 'לא הוגדר'}
- מילות מפתח: {', '.join(profile.harvest_keywords) or 'לא הוגדר'}
- אזורים: {', '.join(profile.operating_regions) or 'לא הוגדר'}
- לקוחות מועדפים: {', '.join(profile.preferred_client_types) or 'לא הוגדר'}

מכרזים שהמשתמש סימן כ-רלוונטיים ({len(liked)}):
{_fmt(liked)}

מכרזים שהמשתמש סימן כ-לא רלוונטיים ({len(disliked)}):
{_fmt(disliked)}

הצע שינויים מינימליים לפרופיל על בסיס הפידבק. ענה ב-JSON בלבד:
{{
  "add_domains": [],
  "remove_domains": [],
  "add_keywords": [],
  "remove_keywords": [],
  "add_negative_patterns": [],
  "add_regions": [],
  "add_client_types": [],
  "explanation_he": "הסבר קצר",
  "summary_he": "סיכום של מה למדנו על החברה"
}}

כללים:
- הצע רק שינויים שנתמכים ברורות ע"י הפידבק
- אל תמחק תחומים שהמשתמש לא התנגד להם מפורשות
- add_negative_patterns: דפוסים ספציפיים בכותרות שמעידים על חוסר רלוונטיות"""

    raw = _call_llm(prompt, "אתה מנתח העדפות חברות קבלן לצורך סינון מכרזים. ענה ב-JSON בלבד.")
    result = json.loads(raw)

    diff = ProfileDiff(
        add_domains=result.get("add_domains", []),
        remove_domains=result.get("remove_domains", []),
        add_keywords=result.get("add_keywords", []),
        remove_keywords=result.get("remove_keywords", []),
        add_negative_patterns=result.get("add_negative_patterns", []),
        add_regions=result.get("add_regions", []),
        add_client_types=result.get("add_client_types", []),
        explanation_he=result.get("explanation_he", ""),
    )
    return FeedbackResponse(diff=diff, summary_he=result.get("summary_he", ""))
