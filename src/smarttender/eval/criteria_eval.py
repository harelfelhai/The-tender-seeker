"""Golden-set evaluation — precision / recall / F1 for criteria extraction.

This is the CI-gateable accuracy number. You hand-label a tender's תנאי סף ONCE
(data/golden/<name>.criteria.json); thereafter every prompt or chunking change
is scored automatically against that ground truth. Without a golden set there is
no trustworthy recall number — this module is where "reliable" comes from.

Matching is lenient on wording but strict on meaning: a predicted criterion
matches a golden one if (field, operator, value) align, or — as a fallback —
their descriptions / key terms are highly similar.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

from ..schemas.tender import TenderAnalysisOutput, TenderCriteriaPredicate

_SIM_THRESHOLD = 0.62


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[֑-ׇ]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _to_num(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v.replace(",", ""))
        return float(m.group()) if m else None
    return None


def _value_match(a: Any, b: Any) -> bool:
    na, nb = _to_num(a), _to_num(b)
    if na is not None and nb is not None:
        return abs(na - nb) < 1e-6
    if isinstance(a, dict) and isinstance(b, dict):
        return {str(k): _norm(str(v)) for k, v in a.items()} == {str(k): _norm(str(v)) for k, v in b.items()}
    return _norm(str(a)) == _norm(str(b))


def _key_terms_overlap(pred_desc: str, gold: dict) -> float:
    terms = gold.get("key_terms") or []
    if not terms:
        return 0.0
    pd = _norm(pred_desc)
    hit = sum(1 for t in terms if _norm(t) in pd)
    return hit / len(terms)


def _matches(pred: TenderCriteriaPredicate, gold: dict) -> bool:
    # Strong: same field + operator + value.
    if (
        _norm(pred.field) == _norm(gold.get("field", ""))
        and pred.operator.value == gold.get("operator")
        and _value_match(pred.value, gold.get("value"))
    ):
        return True
    # Fallback: descriptions are similar, or key terms mostly present.
    sim = SequenceMatcher(None, _norm(pred.description_he), _norm(gold.get("description_he", ""))).ratio()
    return sim >= _SIM_THRESHOLD or _key_terms_overlap(pred.description_he, gold) >= 0.67


@dataclass
class EvalReport:
    golden_total: int
    predicted_total: int
    tp: int
    fp: int
    fn: int
    matched: list[tuple[str, str]] = field(default_factory=list)   # (gold desc, pred id)
    missed: list[dict] = field(default_factory=list)                # golden not found (FN)
    spurious: list[TenderCriteriaPredicate] = field(default_factory=list)  # preds w/o golden (FP)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


def load_golden(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("criteria", [])


def evaluate_against_golden(analysis: TenderAnalysisOutput, golden: list[dict]) -> EvalReport:
    preds = list(analysis.criteria)
    used: set[int] = set()
    matched: list[tuple[str, str]] = []
    missed: list[dict] = []

    for g in golden:
        hit_idx = next(
            (i for i, p in enumerate(preds) if i not in used and _matches(p, g)),
            None,
        )
        if hit_idx is None:
            missed.append(g)
        else:
            used.add(hit_idx)
            matched.append((g.get("description_he", ""), preds[hit_idx].id))

    spurious = [p for i, p in enumerate(preds) if i not in used]
    tp = len(matched)
    return EvalReport(
        golden_total=len(golden),
        predicted_total=len(preds),
        tp=tp,
        fp=len(spurious),
        fn=len(missed),
        matched=matched,
        missed=missed,
        spurious=spurious,
    )
