"""Harvest layer: collect raw tender records from external sources.

Pipeline:
    TenderSource.fetch_new()  →  RawTenderRecord list
    HarvestService.run()      →  persists to raw_tenders, deduplicates
    TenderFilter.should_analyze()  →  PENDING_ANALYSIS | REJECTED
    (trigger) CriteriaAgent  →  TenderAnalysisOutput  →  tenders table
"""
from .base import RawTenderRecord, TenderSource, TenderStatus
from .filter import BasicMetadataFilter, TenderFilter
from .service import HarvestService

__all__ = [
    "RawTenderRecord",
    "TenderSource",
    "TenderStatus",
    "TenderFilter",
    "BasicMetadataFilter",
    "HarvestService",
]
