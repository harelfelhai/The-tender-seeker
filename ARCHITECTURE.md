# SmartTender AI — PoC Architecture & Execution Blueprint

> B2B SaaS for the Israeli market that automates government & municipal tender (מכרזים)
> analysis using Advanced Hebrew RAG and a Multi-Agent AI core.

This document is the engineering blueprint for the Proof of Concept. It deliberately
focuses on the **Core IP** (Hebrew RAG, the multi-agent extraction core, and the Match
Engine) and treats data collection and base models as **bought/outsourced**.

---

## 0. Guiding Principles for the PoC

1. **Validate extraction accuracy before building any API or UI.** The entire value
   proposition collapses if we cannot reliably extract תנאי סף from messy Hebrew PDFs.
   We gate every later sprint behind a measurable accuracy bar.
2. **Hebrew/RTL is a first-class problem, not an afterthought.** Naive PDF text
   extraction reverses RTL word order and mangles tables. We choose tools that are
   proven on Hebrew + layout.
3. **Structured > semantic where possible.** A threshold ("מחזור כספי שנתי של 5 מ׳ ₪
   ב-3 השנים האחרונות") must become a *machine-comparable* predicate, not just a
   retrieved paragraph. The Match Engine is deterministic; the LLM only fills the schema.
4. **One eval harness, used everywhere.** Golden documents + hand-labeled criteria from
   day one. No "vibes-based" iteration.

---

## 1. Detailed Architecture & Tech Stack

### 1.1 Layered architecture

```
                ┌──────────────────────────────────────────────────────────┐
                │ 7. Frontend Dashboard (Next.js/React) — OUT OF CORE SCOPE  │
                └──────────────────────────────────────────────────────────┘
                                          │ REST/WS
                ┌──────────────────────────────────────────────────────────┐
                │ 6. Backend API  (FastAPI, async, Pydantic v2)             │
                │    auth · profile CRUD · search · SSE/WS status           │
                └──────────────────────────────────────────────────────────┘
        ┌─────────────────────────────┬───────────────────────────────────────┐
        │                             │                                       │
┌───────────────┐        ┌────────────────────────┐          ┌──────────────────────────┐
│ 4. Multi-Agent│        │ 5. Core Business DB     │          │ 3. Knowledge Base /       │
│   Orchestrator│◄──────►│   Postgres + SQLAlchemy │◄────────►│    Vector Infra (Qdrant)  │
│  (LangGraph)  │        │   Company/Tender/Logs   │          │    embeddings + metadata  │
└───────────────┘        └────────────────────────┘          └──────────────────────────┘
        ▲                             ▲                                       ▲
        │                             │                                       │
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 2. Async Processing Pipeline (Celery + Redis): extract → OCR → structure → chunk →     │
│    embed → index. Idempotent, retryable, observable.                                    │
└──────────────────────────────────────────────────────────────────────────────────────┘
        ▲
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 1. Data Ingestion Gateway — PoC: watched local dir / upload endpoint (drop PDFs).      │
│    Prod: aggregator API (Yifat/GovTrend) or gov push — OUT OF SCOPE.                    │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Recommended stack (and *why*)

| Concern | Recommendation | Rationale / Hebrew-specific notes |
|---|---|---|
| **PDF parse (digital)** | **PyMuPDF (fitz)** + **pdfplumber** for tables | PyMuPDF handles RTL reading order far better than pdfminer; fast. pdfplumber extracts table cell geometry. |
| **OCR (scanned Hebrew)** | **Azure Document Intelligence** (primary) or **Google Document AI**; **Tesseract `heb`** as offline fallback | Cloud layout models return *tables as structured objects* and handle Hebrew + skew far better than Tesseract. Aligns with build-vs-buy. Tesseract alone is weak on multi-column legal layouts. |
| **RAG / indexing** | **LlamaIndex** | Best-in-class document abstractions: `HierarchicalNodeParser` (Parent-Child), `AutoMergingRetriever`, `SentenceWindowNodeParser`, table nodes. More opinionated for *document* RAG than LangChain. |
| **Agent orchestration** | **LangGraph** | Stateful, deterministic graphs with explicit control flow + retries are ideal for structured extraction agents. (Alternative: LlamaIndex Workflows, if you want a single framework.) |
| **Embeddings** | **Cohere `embed-multilingual-v3.0`** *or* OpenAI `text-embedding-3-large` | Both strong on Hebrew. Cohere pairs natively with its reranker. Open-source alt: **`BAAI/bge-m3`** (dense+sparse+ColBERT, excellent multilingual) for hybrid out of the box. |
| **Re-ranker** | **Cohere `rerank-multilingual-v3.0`** | Reranking is *critical* for תנאי סף precision — first-stage recall is noisy in Hebrew. Open alt: **`BAAI/bge-reranker-v2-m3`**. |
| **Vector DB** | **Qdrant** (Docker, local) | Native hybrid (dense+sparse) search, rich payload filtering (by tender_id/section/page), simple ops. *Consolidation option:* **pgvector** to avoid a second datastore for the PoC. |
| **Extraction LLM** | **Anthropic Claude (Sonnet/Opus)** with enforced JSON schema | Long context for 100+ page docs, strong Hebrew, low hallucination, faithful citation. Use **`instructor`** + Pydantic or native tool-use for guaranteed-valid JSON. |
| **Relational DB** | **PostgreSQL** + SQLAlchemy 2.x + Alembic | Company Profile, Tender JSON (JSONB), audit logs. |
| **Async** | **Celery + Redis** | Background OCR/embedding; Redis doubles as cache + WS pub/sub. |
| **API** | **FastAPI** (Pydantic v2) | Async, typed, SSE/WebSocket for live processing status. |
| **Eval** | **Ragas** (retrieval/faithfulness) + custom criteria-F1 harness | Quantitative gates between sprints. |

### 1.3 The Hebrew RAG pipeline (the hard core)

```
PDF ─► classify(digital|scanned)
     ├─ digital  ─► PyMuPDF text + pdfplumber tables
     └─ scanned  ─► Azure Doc Intelligence (layout+tables) ──► fallback Tesseract heb
                                  │
                                  ▼
            Document Structuring: sections, headings, page anchors
                                  │
        ┌─────────────────────────┴─────────────────────────┐
        ▼ (prose)                                            ▼ (tables)
 HierarchicalNodeParser                          Table → 1 node per table
 (Parent-Child / Auto-Merge)                     • keep rows intact (never split mid-row)
 + SentenceWindow for precision                  • store structured rows in metadata
        └─────────────────────────┬─────────────────────────┘
                                   ▼
        Embed (Cohere/OpenAI) ─► Qdrant (vector + sparse + metadata: tender_id, page,
                                          section, doc_type=criteria|protocol)
                                   ▼
        Retrieve (hybrid, metadata-filtered) ─► Cohere Rerank ─► top-k context
```

**Chunking decision:** Parent-Child / Auto-Merging is the default for legal prose
(retrieve precise children, hand the parent's full context to the LLM). **Tables are
never chunked across rows** — each table becomes one node carrying both a natural-language
summary (for retrieval) and the structured grid in metadata (for the Match Engine).

---

## 2. Data Model Design

### 2.1 `Tender_Criteria` JSON Schema (AI output)

The goal: turn prose תנאי סף into **discrete, machine-comparable predicates** with
provenance. Each criterion carries an `operator` + `value` the Match Engine can evaluate
deterministically, plus a citation and a confidence score for human review.

```jsonc
{
  "tender_id": "MUN-TLV-2026-0142",
  "publisher": { "name_he": "עיריית תל אביב-יפו", "type": "municipality" },
  "title_he": "אספקת והתקנת מערכות מיזוג אוויר",
  "category": "HVAC / works",
  "key_dates": {
    "publication_date": "2026-05-10",
    "questions_deadline": "2026-05-24",
    "submission_deadline": "2026-06-15T12:00:00+03:00"
  },
  "guarantees": {
    "bid_guarantee_ils": 50000,
    "performance_guarantee_pct": 5
  },
  "criteria": [
    {
      "id": "C1",
      "category": "financial",            // financial|experience|certification|classification|insurance|legal|personnel|other
      "description_he": "מחזור כספי שנתי של לפחות 5,000,000 ₪ בכל אחת מ-3 השנים האחרונות",
      "field": "annual_turnover_ils",     // maps to Company_Profile comparable field
      "operator": ">=",                   // >= | <= | == | != | contains | exists | in_range
      "value": 5000000,
      "unit": "ILS",
      "lookback_years": 3,
      "aggregation": "each_year",         // each_year | any_year | cumulative | latest
      "mandatory": true,                  // true = תנאי סף (disqualifying)
      "weight": null,                     // for scored (non-pass/fail) criteria
      "source": { "doc": "criteria.pdf", "page": 12, "section": "4.2", "quote_he": "…" },
      "confidence": 0.93,
      "needs_review": false
    },
    {
      "id": "C2",
      "category": "classification",
      "description_he": "סיווג קבלני ענף 170 (מיזוג אוויר) בקבוצה ג' ובהיקף כספי 3 ומעלה",
      "field": "contractor_classification",
      "operator": "satisfies_classification",
      "value": { "branch": "170", "group": "ג", "financial_tier": 3 },
      "mandatory": true,
      "source": { "doc": "criteria.pdf", "page": 11, "section": "4.1", "quote_he": "…" },
      "confidence": 0.88,
      "needs_review": true
    },
    {
      "id": "C3",
      "category": "experience",
      "description_he": "ניסיון בביצוע 2 פרויקטים דומים לגופים ציבוריים ב-5 השנים האחרונות",
      "field": "similar_public_projects",
      "operator": ">=",
      "value": 2,
      "qualifier": { "client_type": "public", "lookback_years": 5, "min_project_value_ils": null },
      "mandatory": true,
      "source": { "doc": "criteria.pdf", "page": 13, "section": "4.3", "quote_he": "…" },
      "confidence": 0.90
    },
    {
      "id": "C4",
      "category": "certification",
      "description_he": "תקן ISO 9001 בתוקף",
      "field": "certifications",
      "operator": "contains",
      "value": "ISO 9001",
      "mandatory": true,
      "source": { "doc": "criteria.pdf", "page": 14, "section": "4.4", "quote_he": "…" },
      "confidence": 0.95
    }
  ],
  "extraction_meta": {
    "model": "claude-sonnet",
    "schema_version": "1.0",
    "extracted_at": "2026-05-31T10:00:00+03:00",
    "overall_confidence": 0.91
  }
}
```

**`Historical_Insight` (Historical Agent output)** — separate schema for protocol/award PDFs:

```jsonc
{
  "tender_ref": "MUN-TLV-2025-0098",
  "award_date": "2025-09-01",
  "winner": { "name_he": "חברת מיזוג בע\"מ", "company_id": "514xxxxxx" },
  "bids": [
    { "bidder_he": "חברת מיזוג בע\"מ", "price_ils": 4200000, "rank": 1, "disqualified": false },
    { "bidder_he": "אבטחת אקלים בע\"מ", "price_ils": 4550000, "rank": 2, "disqualified": false }
  ],
  "estimate_ils": 4800000,
  "winning_discount_pct": 12.5,
  "notes_he": "…",
  "source": { "doc": "protocol_2025.pdf", "page": 3 },
  "confidence": 0.84
}
```

### 2.2 `Company_Profile` relational schema (PostgreSQL)

Israeli-specific entities are modeled explicitly: **סיווג קבלני** (contractor
classification by branch/group/financial tier), **מחזור** (turnover history), public-body
experience, certs, insurance, and bid guarantees.

```sql
-- Tenants / users
CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE companies (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id      UUID REFERENCES users(id),
  legal_name_he      TEXT NOT NULL,
  company_reg_id     TEXT,                 -- ח.פ / ע.מ
  company_type       TEXT,                 -- ltd | exempt_dealer | licensed_dealer ...
  created_at         TIMESTAMPTZ DEFAULT now()
);

-- Annual financials (turnover per year for lookback comparisons)
CREATE TABLE financial_metrics (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
  fiscal_year     INT NOT NULL,
  annual_turnover_ils  NUMERIC(16,2),
  net_profit_ils       NUMERIC(16,2),
  equity_ils           NUMERIC(16,2),
  UNIQUE (company_id, fiscal_year)
);

-- Contractor classification (סיווג קבלנים): branch + group + financial tier
CREATE TABLE classifications (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
  branch_code     TEXT NOT NULL,          -- e.g. '100', '170'
  group_letter    TEXT,                   -- 'א'..'ה'  (capability group)
  financial_tier  INT,                    -- 1..5
  valid_until     DATE
);

-- Prior projects (experience), incl. public-body flag for "similar public projects"
CREATE TABLE experience_records (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id       UUID REFERENCES companies(id) ON DELETE CASCADE,
  project_name_he  TEXT,
  client_name_he   TEXT,
  client_type      TEXT,                  -- public | private | government | municipal
  project_value_ils NUMERIC(16,2),
  start_date       DATE,
  end_date         DATE,
  domain_tags      TEXT[]                 -- ['HVAC','works'] for similarity matching
);

CREATE TABLE certifications (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    UUID REFERENCES companies(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,            -- 'ISO 9001', 'ISO 45001', ...
  issued_by     TEXT,
  valid_until   DATE
);

CREATE TABLE insurances (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    UUID REFERENCES companies(id) ON DELETE CASCADE,
  insurance_type TEXT,                    -- liability | professional | employer ...
  coverage_ils   NUMERIC(16,2),
  valid_until    DATE
);

-- Tenders: keep AI JSON in JSONB alongside indexed columns
CREATE TABLE tenders (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_ref       TEXT UNIQUE,
  title_he           TEXT,
  publisher_he       TEXT,
  category           TEXT,
  submission_deadline TIMESTAMPTZ,
  criteria_json      JSONB,               -- validated Tender_Criteria
  status             TEXT,                -- ingested|processing|extracted|failed
  created_at         TIMESTAMPTZ DEFAULT now()
);

-- Match results / audit log
CREATE TABLE match_results (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    UUID REFERENCES companies(id),
  tender_id     UUID REFERENCES tenders(id),
  match_score   NUMERIC(5,2),            -- 0..100
  qualifies     BOOLEAN,                 -- all mandatory criteria met?
  breakdown_json JSONB,                  -- per-criterion pass/fail + reason
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE (company_id, tender_id)
);

CREATE TABLE historical_insights (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tender_id     UUID REFERENCES tenders(id),
  insight_json  JSONB,                    -- Historical_Insight schema
  created_at    TIMESTAMPTZ DEFAULT now()
);
```

### 2.3 The Match Engine (deterministic)

The Match Engine is **plain Python**, not an LLM — this keeps qualification decisions
auditable and reproducible.

```
for each criterion in tender.criteria_json:
    field_value   = resolve(company_profile, criterion.field, criterion.qualifier)
    passed, reason = evaluate(criterion.operator, field_value, criterion.value)
    record(criterion.id, passed, reason)

qualifies   = all(mandatory criteria passed)
match_score = weighted blend of (mandatory pass-rate) + (scored criteria) + semantic fit
output: { qualifies, match_score, breakdown:[{id, passed, reason_he, gap}] }
```

The output gives **exact mismatch reasons** (e.g. "מחזור 2024 = 4.1M ₪ < נדרש 5M ₪")
rather than a black-box score. Classification/experience operators (`satisfies_classification`,
similarity-by-domain-tag) live in a small rules module with unit tests.

---

## 3. Phased Development Plan (Sprints)

Each sprint has an explicit **exit gate**. We do **not** start the API/UI until the
extraction gate (Sprint 3) is passed.

| Sprint | Focus | Deliverable | **Exit Gate (measurable)** |
|---|---|---|---|
| **S0 — Foundation** | Repo, Docker (Postgres+Redis+Qdrant), config, sample PDFs in `/data/raw`, eval harness skeleton | Running dev env; 5–10 representative Hebrew tenders (mix digital+scanned) + hand-labeled golden criteria | `docker compose up` works; golden set committed |
| **S1 — Hebrew Parsing & OCR** | Digital + scanned extraction, table fidelity, structuring | `ingestion/` + `pipeline/` produce clean structured text + tables | **Text fidelity ≥ 95%** on golden docs; tables extracted intact (manual spot-check) |
| **S2 — RAG Retrieval** | Chunking (parent-child + table nodes), embed, hybrid retrieve + rerank | Indexed corpus + retrieval API (internal) | **Recall@10 ≥ 0.9** for "which chunks contain each known תנאי סף" (Ragas/manual) |
| **S3 — Criteria Agent ⭐ GATE** | LLM → `Tender_Criteria` JSON w/ schema validation + citations | `agents/criteria_agent.py` + validated JSON per tender | **Criteria F1 ≥ 0.85** vs hand labels; **0 schema-invalid** outputs; citations correct |
| **S4 — Historical Agent** | Parse protocol/award PDFs → pricing/winner insights | `agents/historical_agent.py` + `Historical_Insight` JSON | Winner + price extracted correctly on golden protocols (≥ 0.85) |
| **S5 — Match Engine** | Deterministic evaluation + reasons + score | `match_engine/` + unit tests | All hand-computed match cases pass; reasons exact |
| **S6 — Backend API** | FastAPI: auth, profile CRUD, search, async status (SSE/WS) | Documented OpenAPI; Celery wiring | E2E: upload → process → criteria → match via API |
| **S7 — Frontend** | Dashboard feed by match score + per-doc RAG chat | Next.js app (out of core IP scope) | Demo-ready |

**Why this ordering:** S1→S3 de-risks the only thing that can kill the product
(Hebrew extraction). If F1 stalls at S3, we iterate on OCR/chunking/prompts — *not* on
infrastructure we'd have to rebuild anyway.

---

## 4. Boilerplate Code Structure (Python backend)

```
the-tender-seeker/
├── docker-compose.yml            # postgres + redis + qdrant + api + worker
├── pyproject.toml                # poetry/uv deps
├── .env.example                  # API keys, DB URLs (never commit real keys)
├── README.md
├── ARCHITECTURE.md               # this file
│
├── data/
│   ├── raw/                      # PoC ingestion: drop Hebrew tender PDFs here
│   ├── processed/                # extracted text/tables (cache)
│   └── golden/                   # labeled eval set: *.pdf + *.criteria.json
│
├── src/smarttender/
│   ├── __init__.py
│   ├── config.py                 # pydantic-settings; model/keys/db config
│   │
│   ├── ingestion/                # Layer 1 — Data Ingestion Gateway
│   │   ├── watcher.py            #   watch data/raw (PoC)
│   │   └── upload.py             #   upload endpoint handler
│   │
│   ├── pipeline/                 # Layer 2 — Async Processing
│   │   ├── celery_app.py
│   │   ├── tasks.py              #   orchestrates: extract→ocr→structure→chunk→embed→index
│   │   ├── classify.py           #   digital vs scanned
│   │   ├── extract_digital.py    #   PyMuPDF + pdfplumber
│   │   ├── ocr.py                #   Azure Doc Intelligence / Tesseract fallback
│   │   └── structuring.py        #   sections, headings, page anchors, table nodes
│   │
│   ├── rag/                      # Layer 3 — Knowledge Base / Vector
│   │   ├── chunking.py           #   HierarchicalNodeParser + table-aware nodes
│   │   ├── embeddings.py         #   Cohere/OpenAI client
│   │   ├── vector_store.py       #   Qdrant wrapper (hybrid + metadata filters)
│   │   ├── retriever.py          #   hybrid retrieve + AutoMerging
│   │   └── reranker.py           #   Cohere rerank-multilingual
│   │
│   ├── agents/                   # Layer 4 — Multi-Agent Orchestrator (LangGraph)
│   │   ├── graph.py              #   orchestration graph + state
│   │   ├── criteria_agent.py     #   ⭐ extract Tender_Criteria JSON
│   │   ├── historical_agent.py   #   parse protocols → Historical_Insight
│   │   ├── synthesis_agent.py    #   per-doc RAG chat / Q&A
│   │   └── prompts/              #   versioned Hebrew prompt templates
│   │
│   ├── match_engine/             # Core IP — deterministic evaluation
│   │   ├── engine.py             #   iterate criteria → pass/fail + reasons
│   │   ├── operators.py          #   >=, classification, similarity, etc.
│   │   └── scoring.py            #   match score blend
│   │
│   ├── schemas/                  # Pydantic models (single source of truth)
│   │   ├── tender_criteria.py    #   Tender_Criteria + Criterion
│   │   ├── historical.py         #   Historical_Insight
│   │   └── match.py              #   MatchResult / breakdown
│   │
│   ├── db/                       # Layer 5 — Core Business DB
│   │   ├── models.py             #   SQLAlchemy models (companies, tenders, …)
│   │   ├── session.py
│   │   └── migrations/           #   Alembic
│   │
│   ├── api/                      # Layer 6 — Backend API (FastAPI)
│   │   ├── main.py
│   │   ├── deps.py               #   auth, db session
│   │   └── routers/
│   │       ├── auth.py
│   │       ├── companies.py      #   profile CRUD
│   │       ├── tenders.py        #   list/feed + status (SSE/WS)
│   │       ├── match.py          #   run/get match results
│   │       └── chat.py           #   per-document RAG chat
│   │
│   └── eval/                     # Cross-cutting — accuracy gates
│       ├── retrieval_eval.py     #   recall@k (S2 gate)
│       ├── criteria_eval.py      #   precision/recall/F1 vs golden (S3 gate)
│       └── report.py
│
├── tests/
│   ├── test_match_engine.py
│   ├── test_chunking.py
│   └── test_schemas.py
│
└── frontend/                     # Layer 7 — Next.js (out of core IP scope)
```

---

## 5. Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| RTL/Hebrew text reversal & table mangling | PyMuPDF + cloud layout OCR; table-aware nodes; S1 fidelity gate |
| LLM hallucinating thresholds | Enforced JSON schema (`instructor`/tool-use), mandatory source citations, `needs_review` + confidence, deterministic Match Engine |
| Scanned, low-quality municipal PDFs | Azure/Google Doc AI primary; flag low-confidence pages for human review |
| Israeli-specific semantics (סיווג, מחזור rules) | Modeled explicitly in schema + `operators.py` with unit tests, not left to the LLM |
| Eval drift | Golden set + Ragas + criteria-F1 run in CI on every prompt/chunking change |

---

## 6. Build vs. Buy (confirmed scope)

- **Buy/Outsource:** data collection (Yifat/GovTrend or gov push — PoC simulates via
  `data/raw`), base LLM + embedding + rerank + OCR (managed APIs), frontend component libs.
- **Build (Core IP):** Hebrew RAG pipeline (chunking + table handling + hybrid retrieval +
  rerank), Criteria & Historical agents, and the deterministic Match Engine.
