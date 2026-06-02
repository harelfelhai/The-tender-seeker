"""
Harvest Audit Tool — evaluates filter quality using LLM on metadata only.

The LLM acts as the "teacher" (ground truth). Each run:
  1. Labels all tenders (pending + rejected) as relevant/not
  2. Calculates precision & recall of the deterministic filter vs LLM labels
  3. Saves timestamped labels to data/labels/ for trend tracking
  4. Optionally suggests system-level improvements (taxonomy.py / filter.py)

Usage:
    python scripts/audit/audit.py                  # full audit + metrics
    python scripts/audit/audit.py --fp-only        # only false positive check
    python scripts/audit/audit.py --fn-only        # only false negative check
    python scripts/audit/audit.py --suggest        # also suggest system improvements
    python scripts/audit/audit.py --history        # show metrics trend across past runs

Cost: ~$0.0001 per tender on Haiku. 1000 tenders ≈ $0.10.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console encoding
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import os
os.environ["DATABASE_URL"] = f"sqlite:///{ROOT / 'smarttender.db'}"

import anthropic
from smarttender.api.database import SessionLocal, RawTenderRow, CompanyRow
from smarttender.harvest.base import TenderStatus
from smarttender.schemas.company_profile import CompanyProfile

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 20
MAX_RETRIES = 4
LABELS_DIR = ROOT / "data" / "labels"
CACHE_DIR  = ROOT / "data" / "audit_cache"


# ── prompt ────────────────────────────────────────────────────────────────────

SYSTEM = """אתה מומחה לניתוח מכרזים ממשלתיים ועירוניים בישראל.
תפקידך: להעריך האם מכרז רלוונטי לחברה, על סמך מטא-דאטה בלבד (ללא גישה לתוכן המכרז עצמו).
ענה תמיד ב-JSON בלבד, בלי הסברים מחוץ ל-JSON."""


def _build_prompt(company: CompanyProfile, tenders: list[dict]) -> str:
    summary = (
        f"חברה: {company.company_name}\n"
        f"תחומים: {', '.join(company.domains)}\n"
        f"אזורים: {', '.join(company.operating_regions)}\n"
        f"תקציב מינ׳: {company.min_project_value_ils or 'לא הוגדר'} ₪\n"
        f"תקציב מקס׳: {company.max_project_value_ils or 'לא הוגדר'} ₪"
    )
    return f"""פרופיל החברה:
{summary}

להלן רשימת מכרזים. עבור כל מכרז, קבע האם הוא רלוונטי לחברה על סמך כותרת, נושאים, מפרסם ותקציב בלבד.

מכרזים:
{json.dumps(tenders, ensure_ascii=False, indent=2)}

החזר JSON:
{{
  "results": [
    {{"id": "<id>", "relevant": true/false, "confidence": "high"/"medium"/"low", "reason_he": "<סיבה>"}}
  ]
}}

כללים:
- relevant=true אם קשור ל: מיזוג אויר, קירור, אוורור, פינוי עשן, תחזוקת מערכות מכניות
- relevant=false אם: רכב חשמלי, תאורה, כבלים, גנרטורים, בנייה כללית ללא HVAC
- confidence=high אם ברור; medium אם יש ספק; low אם מידע חסר"""


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_company(db) -> CompanyProfile:
    row = db.query(CompanyRow).first()
    if not row:
        raise RuntimeError("לא נמצאה חברה ב-DB.")
    return CompanyProfile.model_validate_json(row.profile_json)


def _load_tenders(db, status: str) -> list[RawTenderRow]:
    return (
        db.query(RawTenderRow)
        .filter(RawTenderRow.status == status)
        .order_by(RawTenderRow.harvested_at.desc())
        .all()
    )


def _row_to_dict(r: RawTenderRow) -> dict:
    return {
        "id": r.id,
        "title": r.title_he or "",
        "publisher": r.publisher_he or "",
        "subjects": json.loads(r.subjects_json or "[]"),
        "type": r.tender_type or "",
        "budget_ils": r.estimated_budget_ils,
        "deadline": r.deadline.isoformat() if r.deadline else None,
    }


# ── LLM evaluation (with retry) ───────────────────────────────────────────────

def _call_llm(client: anthropic.Anthropic, prompt: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f" [rate-limit, wait {wait}s]", end="", flush=True)
            time.sleep(wait)
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.APIStatusError) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 5 * (2 ** attempt)
            print(f" [retry {attempt+1}/{MAX_RETRIES} in {wait}s]", end="", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _parse_llm_json(raw: str) -> dict:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _cache_path(label: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{label}.json"


def evaluate_tenders(
    client: anthropic.Anthropic,
    company: CompanyProfile,
    rows: list[RawTenderRow],
    cache_label: str = "run",
) -> dict[str, dict]:
    cache = _cache_path(cache_label)

    # Resume from checkpoint if exists
    if cache.exists():
        results: dict[str, dict] = json.loads(cache.read_text(encoding="utf-8"))
        done_ids = set(results.keys())
        rows = [r for r in rows if r.id not in done_ids]
        if rows:
            print(f"  (resuming — {len(done_ids)} cached, {len(rows)} remaining)")
    else:
        results = {}

    total = len(rows)
    already = len(results)

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i: i + BATCH_SIZE]
        n_batch = (total - 1) // BATCH_SIZE + 1 if total else 0
        batch_num = already // BATCH_SIZE + i // BATCH_SIZE + 1
        print(f"  batch {batch_num} ({len(batch)})...", end=" ", flush=True)

        prompt = _build_prompt(company, [_row_to_dict(r) for r in batch])
        parsed = None
        for json_attempt in range(3):
            try:
                raw = _call_llm(client, prompt)
                parsed = _parse_llm_json(raw)
                break
            except json.JSONDecodeError:
                if json_attempt == 2:
                    print(f" [JSON error, skipping batch]", end="", flush=True)
                    parsed = {"results": []}
                else:
                    print(f" [JSON retry {json_attempt+1}]", end="", flush=True)

        for item in (parsed or {}).get("results", []):
            results[item["id"]] = {
                "relevant": item.get("relevant", False),
                "confidence": item.get("confidence", "low"),
                "reason_he": item.get("reason_he", ""),
            }

        # Save checkpoint after every batch
        cache.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        print("✓")

    return results


# ── Precision / Recall ────────────────────────────────────────────────────────

def calc_metrics(
    pending_ids: set[str],
    all_llm_labels: dict[str, dict],
) -> dict:
    """
    Filter decision:  pending_ids  = the set the deterministic filter passed
    LLM ground truth: all_llm_labels[id]["relevant"]

    TP = filter passed AND LLM says relevant
    FP = filter passed AND LLM says not relevant
    FN = filter rejected AND LLM says relevant
    TN = filter rejected AND LLM says not relevant
    """
    tp = sum(1 for tid, v in all_llm_labels.items() if tid in pending_ids and v["relevant"])
    fp = sum(1 for tid, v in all_llm_labels.items() if tid in pending_ids and not v["relevant"])
    fn = sum(1 for tid, v in all_llm_labels.items() if tid not in pending_ids and v["relevant"])
    tn = sum(1 for tid, v in all_llm_labels.items() if tid not in pending_ids and not v["relevant"])

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "llm_relevant_total": tp + fn,
        "filter_passed_total": tp + fp,
    }


# ── Label persistence ─────────────────────────────────────────────────────────

def save_labels(
    run_ts: str,
    company_name: str,
    all_llm_labels: dict[str, dict],
    metrics: dict,
    tender_meta: dict[str, dict],
) -> Path:
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    path = LABELS_DIR / f"{run_ts}.json"
    payload = {
        "run_ts": run_ts,
        "company": company_name,
        "metrics": metrics,
        "labels": {
            tid: {**v, **tender_meta.get(tid, {})}
            for tid, v in all_llm_labels.items()
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_history() -> list[dict]:
    if not LABELS_DIR.exists():
        return []
    runs = []
    for f in sorted(LABELS_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            runs.append({"run_ts": d["run_ts"], "metrics": d["metrics"], "company": d.get("company", "")})
        except Exception:
            pass
    return runs


def print_history():
    history = load_history()
    if not history:
        print("אין היסטוריית הרצות עדיין.")
        return
    print(f"\n{'תאריך':<22} {'Precision':>10} {'Recall':>8} {'F1':>6} {'TP':>5} {'FP':>5} {'FN':>5} {'רלוונטיים':>10}")
    print("-" * 80)
    for r in history:
        m = r["metrics"]
        print(
            f"{r['run_ts']:<22} {m['precision']:>10.3f} {m['recall']:>8.3f} "
            f"{m['f1']:>6.3f} {m['tp']:>5} {m['fp']:>5} {m['fn']:>5} {m['llm_relevant_total']:>10}"
        )


# ── Suggest system improvements ───────────────────────────────────────────────

def _suggest_improvements(
    client: anthropic.Anthropic,
    company: CompanyProfile,
    false_positives: list[dict],
    false_negatives: list[dict],
):
    try:
        from smarttender.harvest.taxonomy import DOMAIN_TERMS, SUBJECT_DOMAIN_MAP, NEGATIVE_PATTERNS
        current_taxonomy = {
            "domain_terms": dict(DOMAIN_TERMS),
            "subject_map": SUBJECT_DOMAIN_MAP,
            "negative_patterns": NEGATIVE_PATTERNS,
        }
    except Exception:
        current_taxonomy = {}

    prompt = f"""אתה מנתח מערכת סינון מכרזים. המשימה: הצע שיפורים ל-taxonomy.py ול-filter.py של המערכת.

פרופיל החברה: תחומים = {', '.join(company.domains)}

הטקסונומיה הנוכחית:
{json.dumps(current_taxonomy, ensure_ascii=False, indent=2)}

False positives (15 ראשונים):
{json.dumps(false_positives[:15], ensure_ascii=False, indent=2)}

False negatives (15 ראשונים):
{json.dumps(false_negatives[:15], ensure_ascii=False, indent=2)}

הצע שיפורים ל**מערכת** (לא למשתמש). ענה ב-JSON:
{{
  "taxonomy_additions": {{"<domain>": ["<term>"]}},
  "taxonomy_removals": {{"<domain>": ["<term>"]}},
  "new_subject_mappings": {{"<subject>": ["<domain>"]}},
  "new_negative_patterns": ["<pattern>"],
  "filter_logic_suggestions": "<הצעות לשינוי לוגיקה>",
  "explanation_he": "<ניתוח>"
}}"""

    raw = _call_llm(client, prompt)
    suggestions = _parse_llm_json(raw)

    print("\nהצעות שיפור למערכת (taxonomy.py / filter.py):")
    if suggestions.get("taxonomy_additions"):
        print("  + הוסף לטקסונומיה:")
        for domain, terms in suggestions["taxonomy_additions"].items():
            print(f"      {domain}: {terms}")
    if suggestions.get("taxonomy_removals"):
        print("  - הסר מטקסונומיה:")
        for domain, terms in suggestions["taxonomy_removals"].items():
            print(f"      {domain}: {terms}")
    if suggestions.get("new_subject_mappings"):
        print("  + subject mappings חדשים:")
        for subj, domains in suggestions["new_subject_mappings"].items():
            print(f"      '{subj}' -> {domains}")
    if suggestions.get("new_negative_patterns"):
        print(f"  X negative patterns חדשים: {suggestions['new_negative_patterns']}")
    if suggestions.get("filter_logic_suggestions"):
        print(f"  >> לוגיקה: {suggestions['filter_logic_suggestions']}")
    print(f"\n  -> {suggestions.get('explanation_he', '')}")

    out = ROOT / "data" / "filter_suggestions.json"
    out.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  נשמר: {out}")


# ── main ──────────────────────────────────────────────────────────────────────

def run_audit(fp: bool = True, fn: bool = True, suggest: bool = False):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY לא מוגדר")

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    client = anthropic.Anthropic(api_key=api_key, max_retries=0)  # manual retry above
    db = SessionLocal()

    try:
        company = _load_company(db)
        print(f"\n=== Audit: {company.company_name} | {run_ts} ===\n")

        pending = _load_tenders(db, TenderStatus.PENDING_ANALYSIS.value)
        rejected = _load_tenders(db, TenderStatus.REJECTED.value)
        pending_ids = {r.id for r in pending}

        all_rows = (pending if fp else []) + (rejected if fn else [])
        tender_meta = {
            r.id: {"title": r.title_he, "filter_decision": "pending" if r.id in pending_ids else "rejected"}
            for r in all_rows
        }

        all_llm_labels: dict[str, dict] = {}

        if fp and pending:
            print(f"[1] False positives — {len(pending)} עברו פילטר")
            all_llm_labels.update(evaluate_tenders(client, company, pending, cache_label="current_pending"))

        if fn and rejected:
            print(f"[2] False negatives — {len(rejected)} נדחו")
            all_llm_labels.update(evaluate_tenders(client, company, rejected, cache_label="current_rejected"))

        # ── Classify results ──────────────────────────────────────────────────
        false_positives = [
            {**tender_meta[tid], **v}
            for tid, v in all_llm_labels.items()
            if tid in pending_ids and not v["relevant"]
        ]
        false_negatives = [
            {**tender_meta[tid], **v}
            for tid, v in all_llm_labels.items()
            if tid not in pending_ids and v["relevant"]
        ]

        print(f"\n   FP: {len(false_positives)} | FN: {len(false_negatives)}")

        # ── Metrics ───────────────────────────────────────────────────────────
        if fp and fn:
            metrics = calc_metrics(pending_ids, all_llm_labels)
            print(
                f"\n   Precision: {metrics['precision']:.3f}  "
                f"Recall: {metrics['recall']:.3f}  "
                f"F1: {metrics['f1']:.3f}"
            )
            print(
                f"   TP={metrics['tp']} FP={metrics['fp']} "
                f"FN={metrics['fn']} TN={metrics['tn']} | "
                f"LLM-relevant={metrics['llm_relevant_total']}"
            )
            labels_path = save_labels(run_ts, company.company_name, all_llm_labels, metrics, tender_meta)
            print(f"   Labels saved: {labels_path}")
        else:
            metrics = {}

        # ── Print details ─────────────────────────────────────────────────────
        if false_positives:
            print("\n── FALSE POSITIVES ──")
            for t in false_positives:
                print(f"  [{t['confidence']}] {t['title'][:65]}")
                print(f"         {t['reason_he']}")

        if false_negatives:
            print("\n── FALSE NEGATIVES ──")
            for t in false_negatives:
                print(f"  [{t['confidence']}] {t['title'][:65]}")
                print(f"         {t['reason_he']}")

        # ── Suggest ───────────────────────────────────────────────────────────
        if suggest and (false_positives or false_negatives):
            print(f"\n[3+4] מציע שיפורים למערכת...")
            _suggest_improvements(client, company, false_positives, false_negatives)

        # ── Save report ───────────────────────────────────────────────────────
        report = {
            "run_ts": run_ts,
            "company": company.company_name,
            "metrics": metrics,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
        }
        out = ROOT / "data" / "audit_report.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nדוח: {out}")

        # Clear checkpoints on success
        for label in ("current_pending", "current_rejected"):
            p = _cache_path(label)
            if p.exists():
                p.unlink()

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fp-only", action="store_true")
    parser.add_argument("--fn-only", action="store_true")
    parser.add_argument("--suggest", action="store_true")
    parser.add_argument("--history", action="store_true", help="Show metrics trend")
    args = parser.parse_args()

    if args.history:
        print_history()
    else:
        run_audit(
            fp=not args.fn_only,
            fn=not args.fp_only,
            suggest=args.suggest,
        )
