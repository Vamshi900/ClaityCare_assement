# Oscar Medical Guidelines — PDF Scraper + Criteria Tree Explorer

## Architecture

```
oscar-app/
├── extraction/     ← Shared module: PDF text extraction, section segmentation, LLM prompts, validation
├── backend/        ← FastAPI: REST API, pipeline orchestration, async LLM calls
├── frontend/       ← React 18 + Vite + Tailwind: policy browser + criteria tree renderer
└── docs/           ← Spec, one-pager, Q&A prep
```

- **Database**: PostgreSQL — policies, downloads, structured trees (with versioning), jobs
- **Storage**: Local filesystem — PDFs and extracted text
- **LLM**: Claude Sonnet 4.6 (Anthropic) — 2-pass extraction + validation
- **State machine**: Each policy progresses through `discovered → downloaded → extracting → validated`

## Quick Start

```bash
cd oscar-app
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY

./setup.sh
```

This installs all dependencies, creates the database, and starts both services.

- **Frontend**: http://localhost:5173
- **Backend**: http://localhost:8000

## Prerequisites

- Python 3.12+ with `venv`
- Node.js 20+ with npm
- PostgreSQL 16+
- Anthropic API key

## Running the Pipeline

### Via UI

Open http://localhost:5173 and use the three buttons:
1. **Discover** — scrapes Oscar's guidelines page, finds all PDF links
2. **Download** — downloads all discovered PDFs
3. **Structure** — extracts criteria trees from 10 PDFs using Claude Sonnet 4.6

### Via API

```bash
# Discover
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "discovery"}'

# Download
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "download"}'

# Structure 10 guidelines
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "structure"}'

# Extract one specific policy
curl -X POST http://localhost:8000/api/policies/{id}/extract

# Check progress
curl http://localhost:8000/api/stats
```

### Via Make

```bash
make start          # Start backend + frontend
make stop           # Stop all services
make restart        # Restart
make status         # Check stats
make extract        # Trigger extraction of 10 policies
make db-reset       # Wipe and recreate database
make logs           # Tail backend logs
```

## Extraction Module

The `extraction/` directory is a standalone, importable module:

```bash
# CLI mode (standalone, no backend needed)
cd extraction
python extractor.py --pdf ../path/to/policy.pdf --output rules.json

# With ground truth comparison
python extractor.py --pdf policy.pdf --output rules.json --validate-against ground_truth.json

# Dry run (no LLM, tests segmentation only)
python test_extraction.py --dry-run
```

The backend imports from this module — no duplicated code.

## Initial-Only Selection Logic

The pipeline uses a 3-tier waterfall heuristic to isolate initial criteria from the full PDF:

**Tier 1: Explicit "Initial" heading** (5 patterns)
- `Initial Authorization Criteria`, `Initial Medical Necessity Criteria`, etc.
- Extracts from heading to first end boundary

**Tier 2: Generic criteria section bounded by continuation markers** (11 patterns)
- Finds `Medical Necessity Criteria`, `Clinical Indications`, etc.
- Stops at `Continuation Criteria`, `Re-authorization`, `Maintenance`, etc.

**Tier 3: Full document fallback**
- If no markers found, sends full text with LLM scope instructions

**TOC skip:** If a match produces a section < 500 chars (likely a table-of-contents entry), it's skipped and the next match is tried. This handles PDFs like CG008 Ver. 11 which have TOC headers before the actual criteria.

Every policy records which tier was used in the `initial_only_method` database column.

## API Reference

```
POST /api/jobs                        Create job (discovery/download/structure)
GET  /api/jobs                        List all jobs
GET  /api/jobs/{id}                   Job detail

GET  /api/policies                    List policies (?search=term)
GET  /api/policies/{id}               Policy detail (includes status)
GET  /api/policies/{id}/tree          Structured criteria tree (?version=N)
GET  /api/policies/{id}/text          Extracted text
GET  /api/policies/{id}/versions      All extraction versions
GET  /api/policies/{id}/pdf-url       PDF file

POST /api/policies/{id}/extract       Trigger extraction for one policy
POST /api/policies/{id}/retry         Retry failed download or extraction

GET  /api/stats                       Dashboard counts
```

## Q&A Notes

See [docs/qa_prep.md](docs/qa_prep.md) for detailed answers to:
- Discovery completeness
- Retries, throttling, idempotency
- Initial-only selection logic and failure modes
- LLM validation and malformed JSON handling
- UI tree rendering approach
