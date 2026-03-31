# Oscar Medical Guidelines — PDF Scraper + Criteria Tree Explorer

**Live Demo:** http://187.77.16.252:5173 | **API:** http://187.77.16.252:8000

Scrapes Oscar Health's medical clinical guideline PDFs, extracts initial medical necessity criteria using a 2-pass LLM pipeline, and renders them as interactive decision trees.

## Contents

- [How It Works](#how-it-works)
- [Try the Extraction (standalone)](#try-the-extraction-standalone)
- [Quick Start (full app)](#quick-start-full-app)
- [Project Structure](#project-structure)
- [Module Docs](#module-docs)
- [Initial-Only Selection Logic](#initial-only-selection-logic)
- [Local Setup (detailed)](#local-setup-detailed)

---

## How It Works

```
                        ┌─────────────────────────────────────────┐
                        │              Oscar Website              │
                        └──────────────┬──────────────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │         1. DISCOVERY                 │
                    │   __NEXT_DATA__ + HTML scraping       │
                    │   207 guidelines found                │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │         2. DOWNLOAD                   │
                    │   httpx + retry + rate limit           │
                    │   PDFs → storage/pdfs/                │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │         3. EXTRACTION                 │
                    │   PDF → text → segment → LLM (2-pass) │
                    │   → validate → JSON decision tree     │
                    └──────────────────┬──────────────────┘
                                       │
                    ┌──────────────────▼──────────────────┐
                    │         4. UI                         │
                    │   Browse policies, view trees          │
                    │   Expand/collapse, AND/OR badges       │
                    └──────────────────────────────────────┘
```

Each policy moves through states: `discovered → downloaded → extracting → validated`

The extraction module is **standalone** — it works as a CLI tool or as an imported library.

---

## Try the Extraction (standalone)

No backend needed. Just the extraction module + a PDF + an API key:

```bash
cd extraction
pip install -r requirements.txt

# Extract criteria from any guideline PDF
ANTHROPIC_API_KEY=sk-ant-... python extractor.py \
  --pdf ../full-stack-feb/oscar.pdf \
  --output rules.json

# Compare against ground truth
ANTHROPIC_API_KEY=sk-ant-... python extractor.py \
  --pdf ../full-stack-feb/oscar.pdf \
  --output rules.json \
  --validate-against ../full-stack-feb/oscar.json

# Dry run (no LLM, test segmentation only)
python test_extraction.py --dry-run
```

---

## Quick Start (full app)

```bash
cd oscar-app
cp .env.example .env          # Add your ANTHROPIC_API_KEY
chmod +x setup.sh
./setup.sh                     # Installs everything, starts services
```

Open http://localhost:5173, click **Discover → Download → Structure**.

---

## Project Structure

```
oscar-app/
├── extraction/          Standalone extraction module (CLI + importable library)
│   ├── segmenter.py       PDF text extraction + section segmentation
│   ├── prompts.py         LLM prompt templates (extraction + validation)
│   ├── validator.py       JSON schema + integrity checks
│   ├── llm_client.py      Sync Anthropic client (for CLI mode)
│   └── extractor.py       Pipeline orchestrator + CLI
│
├── backend/             FastAPI REST API + pipeline orchestration
│   ├── app/main.py        All routes + background job runners
│   ├── app/llm/client.py  Async LLM adapter (Anthropic + OpenAI)
│   ├── app/pipelines/     discoverer, downloader, structurer
│   └── db/                Schema + migrations
│
├── frontend/            React 18 + Vite + Tailwind
│   └── src/
│       ├── components/    PolicyList, PolicyDetail, CriteriaTree, TreeNode, StateBar
│       └── hooks/         usePolicies, useTree, useText, useVersions
│
├── docs/                Module documentation
├── setup.sh             One-command setup
└── Makefile             start, stop, extract, db-reset, status
```

Backend **imports from** `extraction/` — no duplicated code.

---

## Module Docs

| Module | Doc | What it does |
|--------|-----|-------------|
| Discovery | [oscar-app/docs/discovery.md](oscar-app/docs/discovery.md) | Scrapes guideline page, finds all PDF URLs |
| Download | [oscar-app/docs/download.md](oscar-app/docs/download.md) | Downloads PDFs with retry + rate limiting |
| Extraction | [oscar-app/docs/extraction.md](oscar-app/docs/extraction.md) | 2-pass LLM pipeline: PDF → JSON decision tree |
| Frontend | [oscar-app/docs/frontend.md](oscar-app/docs/frontend.md) | Policy browser + interactive tree renderer |
| API | [oscar-app/docs/api.md](oscar-app/docs/api.md) | REST endpoint reference |

---

## Initial-Only Selection Logic

Many guidelines have both Initial and Continuation criteria. We extract only Initial using a 3-tier waterfall:

```
Tier 1: Explicit "Initial Criteria" heading     → 5 regex patterns
         ↓ (not found or < 500 chars)
Tier 2: Generic criteria, bounded by             → 4 start + 11 continuation
        continuation/end markers                    + 7 end markers
         ↓ (not found or < 500 chars)
Tier 3: Full document fallback                   → LLM prompt scopes it
```

If a match produces < 500 chars (table-of-contents entry), it's skipped. Method recorded per policy in DB.

---

## Local Setup (detailed)

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 16+
- Anthropic API key

### Step-by-step

```bash
# 1. Environment
cd oscar-app
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY

# 2. Database
sudo -u postgres psql -c "CREATE DATABASE oscar_guidelines;"
sudo -u postgres psql -c "CREATE USER oscar WITH PASSWORD 'oscar_dev_pw';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE oscar_guidelines TO oscar;"
sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON SCHEMA public TO oscar;"
sudo -u postgres psql -d oscar_guidelines < backend/db/init.sql
sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON ALL TABLES IN SCHEMA public TO oscar;"
sudo -u postgres psql -d oscar_guidelines -c "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO oscar;"
sudo -u postgres psql -d oscar_guidelines < backend/db/migrate_001_status.sql

# 3. Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.bootstrap
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
  --reload-dir app --reload-dir ../extraction &
cd ..

# 4. Frontend
cd frontend
npm install
npx vite --host 0.0.0.0 &
cd ..

# 5. Run pipeline
curl -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d '{"type":"discovery"}'
# Wait ~2 min
curl -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d '{"type":"download"}'
# Wait ~3 min
curl -X POST http://localhost:8000/api/jobs -H "Content-Type: application/json" -d '{"type":"structure"}'
# Wait ~5 min

# 6. Open UI
open http://localhost:5173
```

### Make commands

```bash
make start          # Start backend + frontend
make stop           # Stop all
make restart        # Restart both
make status         # Check stats
make extract        # Trigger extraction of 10 policies
make db-reset       # Wipe and recreate database
make logs           # Tail backend logs
```
