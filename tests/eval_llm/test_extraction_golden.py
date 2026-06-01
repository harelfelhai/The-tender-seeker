"""End-to-end extraction accuracy tests against hand-labeled golden fixtures.

Each test:
  1. Loads a golden .criteria.json hand-labeled by us.
  2. Feeds the tender text to CriteriaAgent (Haiku — cheap, fast).
  3. Scores precision / recall / F1 via evaluate_against_golden.
  4. Asserts thresholds — a regression in the prompt or schema triggers a failure.

Run:
    pytest -m eval                          # all LLM eval tests
    pytest -m eval -s                       # with extraction status messages
    pytest -m eval tests/eval_llm/test_extraction_golden.py::test_hvac_recall

Thresholds are intentionally lenient (Haiku) — the point is regression detection,
not perfection.  Tighten them once production uses Sonnet/Opus.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.smarttender.agents.criteria_agent import CriteriaAgent
from src.smarttender.eval.criteria_eval import evaluate_against_golden, load_golden

# Repo root relative to this file (tests/eval_llm/ → ../../)
_ROOT = Path(__file__).parent.parent.parent

# Minimum acceptable scores for Haiku on our synthetic tenders.
# Recall is weighted higher than precision — missing a mandatory criterion is worse
# than extracting an extra one.
_MIN_RECALL = 0.70
_MIN_PRECISION = 0.60
_MIN_F1 = 0.65


def _agent() -> CriteriaAgent:
    return CriteriaAgent(model="haiku", fallback_to_mock=False, use_cache=True)


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── fixtures ──────────────────────────────────────────────────────────────────

GOLDEN_FIXTURES = [
    # (golden_json_path, source_text_path, human_label)
    (
        _ROOT / "data/golden/sample_tender_he.criteria.json",
        None,  # PDF — extract via pdf_path
        "HVAC tender (Tel Aviv municipality)",
    ),
    (
        _ROOT / "data/golden/tender_cleaning_he.criteria.json",
        _ROOT / "data/golden/tender_cleaning_he.txt",
        "Cleaning services tender (Haifa municipality)",
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
# Parameterised golden tests
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.eval
@pytest.mark.parametrize("golden_path,text_path,label", GOLDEN_FIXTURES, ids=["hvac", "cleaning"])
def test_extraction_recall(golden_path, text_path, label, capsys):
    """Recall ≥ _MIN_RECALL — we must not miss most mandatory criteria."""
    golden = load_golden(str(golden_path))
    agent = _agent()

    statuses: list[str] = []
    if text_path is not None:
        text = _load_text(text_path)
        analysis = agent.extract(text=text, on_status=statuses.append)
    else:
        pdf_path = str(_ROOT / "data/raw/sample_tender_he.pdf")
        analysis = agent.extract(pdf_path=pdf_path, on_status=statuses.append)

    with capsys.disabled():
        for s in statuses:
            print(f"  [status] {s}")

    report = evaluate_against_golden(analysis, golden)

    print(f"\n{label}")
    print(f"  predicted={report.predicted_total}  golden={report.golden_total}")
    print(f"  TP={report.tp}  FP={report.fp}  FN={report.fn}")
    print(f"  precision={report.precision:.2f}  recall={report.recall:.2f}  F1={report.f1:.2f}")
    if report.missed:
        print("  MISSED (FN):")
        for m in report.missed:
            print(f"    - {m.get('description_he', m)}")

    assert report.recall >= _MIN_RECALL, (
        f"{label}: recall {report.recall:.2f} < {_MIN_RECALL}. "
        f"Missed: {[m.get('description_he') for m in report.missed]}"
    )


@pytest.mark.eval
@pytest.mark.parametrize("golden_path,text_path,label", GOLDEN_FIXTURES, ids=["hvac", "cleaning"])
def test_extraction_precision(golden_path, text_path, label, capsys):
    """Precision ≥ _MIN_PRECISION — extracted criteria must be real, not hallucinated."""
    golden = load_golden(str(golden_path))
    agent = _agent()

    if text_path is not None:
        text = _load_text(text_path)
        analysis = agent.extract(text=text, on_status=lambda _: None)
    else:
        pdf_path = str(_ROOT / "data/raw/sample_tender_he.pdf")
        analysis = agent.extract(pdf_path=pdf_path, on_status=lambda _: None)

    report = evaluate_against_golden(analysis, golden)

    if report.spurious:
        with capsys.disabled():
            print(f"\n{label} — spurious (FP):")
            for p in report.spurious:
                print(f"    - {p.description_he}")

    assert report.precision >= _MIN_PRECISION, (
        f"{label}: precision {report.precision:.2f} < {_MIN_PRECISION}. "
        f"Spurious: {[p.description_he for p in report.spurious]}"
    )


@pytest.mark.eval
@pytest.mark.parametrize("golden_path,text_path,label", GOLDEN_FIXTURES, ids=["hvac", "cleaning"])
def test_extraction_f1(golden_path, text_path, label):
    """F1 ≥ _MIN_F1 — combined accuracy gate."""
    golden = load_golden(str(golden_path))
    agent = _agent()

    if text_path is not None:
        text = _load_text(text_path)
        analysis = agent.extract(text=text, on_status=lambda _: None)
    else:
        pdf_path = str(_ROOT / "data/raw/sample_tender_he.pdf")
        analysis = agent.extract(pdf_path=pdf_path, on_status=lambda _: None)

    report = evaluate_against_golden(analysis, golden)
    assert report.f1 >= _MIN_F1, (
        f"{label}: F1 {report.f1:.2f} < {_MIN_F1} "
        f"(P={report.precision:.2f}, R={report.recall:.2f})"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Mandatory-only recall — the highest-stakes sub-metric
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.eval
@pytest.mark.parametrize("golden_path,text_path,label", GOLDEN_FIXTURES, ids=["hvac", "cleaning"])
def test_mandatory_criteria_recall(golden_path, text_path, label):
    """Recall on mandatory-only criteria ≥ 0.75.

    A missed mandatory criterion is a false negative that could cause a
    company to participate in a tender they can't win — the worst failure mode.
    """
    golden_all = load_golden(str(golden_path))
    golden_mandatory = [g for g in golden_all if g.get("mandatory", True)]
    if not golden_mandatory:
        pytest.skip("no mandatory criteria in golden")

    agent = _agent()
    if text_path is not None:
        text = _load_text(text_path)
        analysis = agent.extract(text=text, on_status=lambda _: None)
    else:
        pdf_path = str(_ROOT / "data/raw/sample_tender_he.pdf")
        analysis = agent.extract(pdf_path=pdf_path, on_status=lambda _: None)

    report = evaluate_against_golden(analysis, golden_mandatory)
    assert report.recall >= 0.75, (
        f"{label} mandatory recall {report.recall:.2f} < 0.75. "
        f"Missed mandatory: {[m.get('description_he') for m in report.missed]}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Structural sanity (no LLM call, fast)
# ══════════════════════════════════════════════════════════════════════════════

def test_golden_files_are_valid():
    """Golden JSON files parse correctly and have required keys — no LLM needed."""
    for golden_path, _, label in GOLDEN_FIXTURES:
        assert golden_path.exists(), f"Golden file missing: {golden_path}"
        data = json.loads(golden_path.read_text(encoding="utf-8"))
        assert "criteria" in data, f"{label}: missing 'criteria' key"
        for i, c in enumerate(data["criteria"]):
            for key in ("category", "field", "operator", "value", "mandatory", "description_he"):
                assert key in c, f"{label} criterion[{i}] missing '{key}'"
        print(f"  {label}: {len(data['criteria'])} criteria OK")


def test_text_fixtures_exist():
    """Source text/PDF fixtures referenced in golden files all exist on disk."""
    for _, text_path, label in GOLDEN_FIXTURES:
        if text_path is not None:
            assert text_path.exists(), f"{label}: text fixture missing at {text_path}"
    # HVAC uses the PDF
    pdf_path = _ROOT / "data/raw/sample_tender_he.pdf"
    assert pdf_path.exists(), f"HVAC PDF fixture missing at {pdf_path}"
