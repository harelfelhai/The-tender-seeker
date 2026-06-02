from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TenderFeedback(BaseModel):
    """User feedback on a scored tender — the FUTURE ML training label.

    Designed now (even though scoring is rule-based today) so that every user
    decision is captured from day one. Once enough rows accumulate, these labels
    let an ML model learn the relevance weights that today are hand-tuned.

    Relational target (later):
        tender_feedback(company_id, tender_id, predicted_score, was_relevant,
                        did_pursue, did_win, created_at)
    """

    company_id: str
    tender_id: str
    predicted_score: float = Field(ge=0.0, le=100.0)

    # explicit user signals
    was_relevant: Optional[bool] = Field(
        default=None, description="Did the user consider this tender relevant?"
    )
    did_pursue: Optional[bool] = Field(
        default=None, description="Did the company decide to bid?"
    )
    did_win: Optional[bool] = Field(default=None, description="Did the company win?")

    note_he: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
