"""ManualSource: wraps a single user-uploaded PDF as a RawTenderRecord.

Manual uploads bypass the filter (user made a deliberate choice) and enter
the pipeline at PENDING_ANALYSIS status.  This source is not called via
the harvest scheduler — it is invoked directly by the /tenders/ingest endpoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..base import RawTenderRecord


class ManualSource:
    source_id = "manual"

    async def fetch_new(
        self,
        since: Optional[datetime] = None,
    ) -> list[RawTenderRecord]:
        # Manual uploads are created on demand — nothing to poll.
        return []

    @staticmethod
    def make_record(
        filename: str,
        pdf_bytes: bytes,
        uploaded_by: str,
    ) -> RawTenderRecord:
        """Build a RawTenderRecord for a manually uploaded PDF."""
        return RawTenderRecord(
            source_id="manual",
            external_id=f"manual__{uploaded_by}__{filename}",
            title_he=filename,
            uploaded_by=uploaded_by,
            pdf_blob=pdf_bytes,
            raw_metadata={"filename": filename, "uploaded_by": uploaded_by},
        )
