"""Deterministic orchestration of the analysis pipeline.

Today this is plain Python: an explicit, debuggable sequence of nodes that
share a single PipelineState.  Each method is a self-contained "node" with a
clear (state) -> state contract — so migrating to LangGraph later is mechanical
(register each method as a node, keep the same state object).  We do NOT pull in
a multi-agent framework until a real need appears (loops, conditional routing,
human-in-the-loop).  See ARCHITECTURE.md §1.2 and the discussion in the README.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..match_engine.engine import evaluate_match
from ..schemas.company_profile import CompanyProfile
from ..schemas.match import MatchReport
from ..schemas.tender import TenderAnalysisOutput
from .criteria_agent import CriteriaAgent, StatusFn, _noop


@dataclass
class PipelineState:
    """Shared state threaded through every node (LangGraph-ready)."""

    company: CompanyProfile
    pdf_path: Optional[str] = None
    text: Optional[str] = None
    fallback_to_mock: bool = True

    # produced by nodes
    analysis: Optional[TenderAnalysisOutput] = None
    report: Optional[MatchReport] = None
    log: list[str] = field(default_factory=list)


class TenderPipeline:
    """Orchestrates: extract criteria → run match engine.

    Add nodes here (e.g. historical_agent, reranker eval) as the system grows.
    """

    def __init__(self, criteria_agent: Optional[CriteriaAgent] = None) -> None:
        self.criteria_agent = criteria_agent or CriteriaAgent()

    # ── nodes ────────────────────────────────────────────────────────────────
    def node_extract_criteria(self, state: PipelineState, *, on_status: StatusFn = _noop) -> PipelineState:
        def _status(msg: str) -> None:
            state.log.append(msg)
            on_status(msg)

        state.analysis = self.criteria_agent.extract(
            pdf_path=state.pdf_path,
            text=state.text,
            fallback_to_mock=state.fallback_to_mock,
            on_status=_status,
        )
        return state

    def node_run_match(self, state: PipelineState, *, on_status: StatusFn = _noop) -> PipelineState:
        if state.analysis is None:
            raise RuntimeError("node_run_match called before criteria were extracted")
        state.report = evaluate_match(state.company, state.analysis)
        on_status("מנוע ההתאמה הושלם")
        return state

    # ── driver ───────────────────────────────────────────────────────────────
    def run(self, state: PipelineState, *, on_status: StatusFn = _noop) -> PipelineState:
        state = self.node_extract_criteria(state, on_status=on_status)
        state = self.node_run_match(state, on_status=on_status)
        return state
