# Oscar Medical Guidelines — Full Implementation Spec

## For: Claude Code Agent Execution
## Author: Vamshi (with Claude analysis)
## Date: 2026-03-31

---

## 1. SYSTEM OVERVIEW

Build an end-to-end pipeline that discovers, downloads, and structures Oscar Health's medical clinical guideline PDFs into navigable JSON decision trees, exposed via a React UI.

### Architecture: 4 Services + Docker Compose

```
┌──────────────────────────────────────────────────────────────────┐
│                        Docker Compose                            │
│                                                                  │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────────┐  │
│  │   Valkey     │   │  PostgreSQL   │   │     MinIO (S3)      │  │
│  │  (Streams)   │   │  (Data Store) │   │   (Blob Storage)    │  │
│  │  port: 6379  │   │  port: 5432   │   │   port: 9000/9001   │  │
│  └──────┬───────┘   └──────┬────────┘   └──────────┬──────────┘  │
│         │                  │                       │             │
│  ┌──────┴──────────────────┴───────────────────────┴──────────┐  │
│  │                     Backend (FastAPI)                       │  │
│  │                      port: 8000                            │  │
│  │   /api/discover  /api/download  /api/structure  /api/...   │  │
│  └──────────────────────────┬─────────────────────────────────┘  │
│                             │                                    │
│  ┌──────────────────────────┴─────────────────────────────────┐  │
│  │                   Frontend (React + Vite)                   │  │
│  │                      port: 5173                            │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### State Machine via Valkey Streams

Each pipeline stage is a stream consumer. State transitions:

```
DISCOVERY ──stream:discovered──▶ DOWNLOAD ──stream:downloaded──▶ STRUCTURING
                                                                      │
                                                              stream:structured
                                                                      │
                                                                      ▼
                                                               DB + MinIO
```

Stream names:
- `stream:discovery-tasks` — triggers PDF discovery
- `stream:download-tasks` — policy_id to download
- `stream:structure-tasks` — policy_id to structure (for selected 10+)
- `stream:events` — general event log for UI status updates

Consumer groups:
- `cg:downloader` — consumes from `stream:download-tasks`
- `cg:structurer` — consumes from `stream:structure-tasks`

---

## 2. INFRASTRUCTURE SERVICES

### 2.1 Docker Compose File

File: `docker-compose.yml`

```yaml
version: "3.9"

services:
  valkey:
    image: valkey/valkey:8-alpine
    ports:
      - "6379:6379"
    volumes:
      - valkey_data:/data
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: oscar_guidelines
      POSTGRES_USER: oscar
      POSTGRES_PASSWORD: oscar_dev_pw
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./backend/db/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U oscar -d oscar_guidelines"]
      interval: 5s
      timeout: 3s
      retries: 5

  minio:
    image: minio/minio:latest
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 3s
      retries: 5

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+asyncpg://oscar:oscar_dev_pw@postgres:5432/oscar_guidelines
      VALKEY_URL: valkey://valkey:6379/0
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin123
      MINIO_BUCKET: oscar-pdfs
      MINIO_USE_SSL: "false"
    depends_on:
      postgres:
        condition: service_healthy
      valkey:
        condition: service_healthy
      minio:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: >
      sh -c "python -m app.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    environment:
      VITE_API_URL: http://localhost:8000
    depends_on:
      - backend

volumes:
  valkey_data:
  pg_data:
  minio_data:
```

### 2.2 Why These Choices

| Service | Why | Alternative Considered |
|---------|-----|----------------------|
| **PostgreSQL** | Real relational DB, supports JSON columns natively, production-grade | SQLite (too simple for stream-based arch) |
| **Valkey** | Redis-compatible streams for state machine, lightweight pub/sub for UI events | RabbitMQ (overkill), direct function calls (no decoupling) |
| **MinIO** | S3-compatible blob storage for PDFs and extracted text, self-hosted | Local filesystem (not realistic), actual S3 (needs AWS account) |

### 2.3 MinIO Bucket Setup

The `bootstrap.py` script (runs before FastAPI starts) creates the bucket:

```python
# backend/app/bootstrap.py
from minio import Minio
import os

def setup_minio():
    client = Minio(
        os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
        secure=os.getenv("MINIO_USE_SSL", "false").lower() == "true",
    )
    bucket = os.getenv("MINIO_BUCKET", "oscar-pdfs")
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    print(f"MinIO bucket '{bucket}' ready")

def setup_valkey_streams():
    """Create consumer groups if they don't exist."""
    import valkey
    r = valkey.from_url(os.getenv("VALKEY_URL", "valkey://valkey:6379/0"))
    streams = {
        "stream:download-tasks": "cg:downloader",
        "stream:structure-tasks": "cg:structurer",
    }
    for stream, group in streams.items():
        try:
            r.xgroup_create(stream, group, id="0", mkstream=True)
        except valkey.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
    print("Valkey streams ready")

if __name__ == "__main__":
    setup_minio()
    setup_valkey_streams()
```

---

## 3. DATABASE SCHEMA

File: `backend/db/init.sql`

```sql
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- POLICIES: Every discovered guideline from the source page
-- ============================================================
CREATE TABLE IF NOT EXISTS policies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    guideline_code  TEXT,                -- e.g., "CG008", "PG136"
    version         TEXT,                -- e.g., "Ver. 11"
    pdf_url         TEXT NOT NULL UNIQUE, -- idempotency key
    source_page_url TEXT NOT NULL,
    discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_policies_pdf_url ON policies(pdf_url);
CREATE INDEX idx_policies_guideline_code ON policies(guideline_code);

-- ============================================================
-- DOWNLOADS: Track every download attempt per policy
-- ============================================================
CREATE TABLE IF NOT EXISTS downloads (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id       UUID NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    stored_location TEXT,                -- MinIO object key: "pdfs/{guideline_code}.pdf"
    downloaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status     INTEGER,
    file_size_bytes BIGINT,
    content_hash    TEXT,                -- SHA-256 for dedup
    error           TEXT,                -- NULL = success
    attempt_number  INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_downloads_policy_id ON downloads(policy_id);

-- ============================================================
-- STRUCTURED_POLICIES: LLM-extracted criteria trees (10+ min)
-- ============================================================
CREATE TABLE IF NOT EXISTS structured_policies (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id         UUID NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    extracted_text_ref TEXT,             -- MinIO object key: "text/{guideline_code}.txt"
    structured_json   JSONB NOT NULL,    -- The criteria tree matching oscar.json schema
    structured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    llm_metadata      JSONB NOT NULL,    -- { "model": "...", "prompt_version": "...", "tokens_used": ... }
    validation_error  TEXT,              -- NULL = passed validation
    initial_only_method TEXT,            -- How "initial" was selected
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_structured_policy_id ON structured_policies(policy_id);

-- ============================================================
-- PIPELINE_RUNS: Track each pipeline execution for observability
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage       TEXT NOT NULL,           -- 'discovery', 'download', 'structuring'
    status      TEXT NOT NULL DEFAULT 'running', -- 'running', 'completed', 'failed'
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    metadata    JSONB,                   -- { "total": 85, "success": 83, "failed": 2 }
    error       TEXT
);
```

### Storage Layout in MinIO

```
oscar-pdfs/                    (bucket)
├── pdfs/
│   ├── CG008_v11.pdf          (downloaded guideline PDFs)
│   ├── CG013_v11.pdf
│   └── ...
└── text/
    ├── CG008_v11.txt          (extracted full text, blob)
    ├── CG013_v11.txt
    └── ...
```

Text is stored as blob in MinIO (not in Postgres) because:
- Some PDFs extract to 50KB+ of text
- Keeps Postgres rows lean for fast queries
- `extracted_text_ref` column points to the MinIO object key
- Structured JSON stays in Postgres (JSONB) for querying

---

## 4. BACKEND SERVICE (FastAPI)

### 4.1 Project Structure

```
backend/
├── Dockerfile
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, routes, CORS
│   ├── bootstrap.py            # MinIO + Valkey setup
│   ├── config.py               # Settings from env
│   ├── db.py                   # Async SQLAlchemy engine/session
│   ├── models.py               # SQLAlchemy ORM models
│   ├── schemas.py              # Pydantic request/response models
│   ├── minio_client.py         # MinIO helper (upload/download/presigned URLs)
│   ├── valkey_client.py        # Valkey stream helpers
│   │
│   ├── pipelines/
│   │   ├── __init__.py
│   │   ├── discoverer.py       # Scrape source page, find all PDF links
│   │   ├── downloader.py       # Download PDFs to MinIO with retry
│   │   ├── extractor.py        # PDF text extraction (pypdf)
│   │   ├── structurer.py       # LLM call + validation
│   │   └── orchestrator.py     # Wire up the full pipeline or individual stages
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── prompt.py           # System prompt + few-shot example
│   │   ├── client.py           # OpenAI API wrapper
│   │   └── validator.py        # Pydantic schema for oscar.json tree
│   │
│   └── workers/
│       ├── __init__.py
│       ├── download_worker.py  # Valkey stream consumer for downloads
│       └── structure_worker.py # Valkey stream consumer for structuring
```

### 4.2 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps for PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4.3 Requirements

```
# backend/requirements.txt
fastapi==0.115.*
uvicorn[standard]==0.34.*
sqlalchemy[asyncio]==2.0.*
asyncpg==0.30.*
pydantic==2.10.*
httpx==0.28.*
beautifulsoup4==4.13.*
pypdf==5.1.*
openai==1.61.*
minio==7.2.*
valkey==6.1.*
python-dotenv==1.0.*
```

### 4.4 Key Config

```python
# backend/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    valkey_url: str = "valkey://valkey:6379/0"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_bucket: str = "oscar-pdfs"
    minio_use_ssl: bool = False
    openai_api_key: str
    oscar_source_url: str = "https://www.hioscar.com/clinical-guidelines/medical"
    llm_model: str = "gpt-4o"
    llm_structuring_batch_size: int = 10

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 5. PIPELINE DETAILS

### 5.1 Discovery (`discoverer.py`)

**Goal**: Scrape the Oscar medical guidelines page and extract ALL guideline PDF links.

**Approach** (try in order):

1. **Fetch raw HTML** of `https://www.hioscar.com/clinical-guidelines/medical` with httpx
2. **Check for `__NEXT_DATA__`** JSON blob in `<script id="__NEXT_DATA__">` — if present, parse the JSON to find guideline entries (title, URL). This is the fastest path.
3. **If no `__NEXT_DATA__`**, look for `<a>` tags whose `href` matches patterns:
   - `/medical/cg{NNN}v{NN}` — guideline page links
   - `assets.ctfassets.net/.../*.pdf` — direct PDF links
4. **If page is JS-rendered** (empty body), fall back to fetching the known pattern: each guideline has a page URL like `https://www.hioscar.com/medical/{code}` which contains a PDF link. Use the visible guideline listing text to build these URLs.

**For each guideline found:**

```python
# Pseudocode
async def discover_guidelines(source_url: str) -> list[dict]:
    resp = await httpx.get(source_url, follow_redirects=True, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategy 1: __NEXT_DATA__
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data:
        data = json.loads(next_data.string)
        # Navigate the JSON to find guideline entries
        # Look for props.pageProps or similar structure
        guidelines = extract_from_next_data(data)
        if guidelines:
            return guidelines

    # Strategy 2: Direct link scraping
    guidelines = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        # Match PDF links or guideline page links
        if "ctfassets.net" in href and href.endswith(".pdf"):
            guidelines.append({
                "title": link.get_text(strip=True),
                "pdf_url": href,
                "source_page_url": source_url,
            })
        elif re.match(r"/medical/(cg|pg)\d+", href, re.I):
            # Need to visit this page to find the PDF link
            guidelines.append({
                "title": link.get_text(strip=True),
                "page_url": urljoin(source_url, href),
                "source_page_url": source_url,
            })

    # Strategy 2b: For page_url entries, fetch each to find PDF
    for g in guidelines:
        if "page_url" in g and "pdf_url" not in g:
            pdf_url = await resolve_pdf_from_page(g["page_url"])
            g["pdf_url"] = pdf_url

    return guidelines
```

**Idempotency**: Use `INSERT ... ON CONFLICT (pdf_url) DO NOTHING` when storing policies.

**After discovery**: For each new policy stored, publish to `stream:download-tasks`:
```python
valkey.xadd("stream:download-tasks", {"policy_id": str(policy.id), "pdf_url": policy.pdf_url})
```

### 5.2 Download (`downloader.py`)

**Goal**: Download all discovered PDFs to MinIO with retry and rate limiting.

```python
MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds
RATE_LIMIT_DELAY = 0.5  # seconds between requests

async def download_pdf(policy_id: str, pdf_url: str) -> DownloadResult:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            await asyncio.sleep(RATE_LIMIT_DELAY)  # polite scraping

            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(pdf_url)
                resp.raise_for_status()

            content = resp.content
            content_hash = hashlib.sha256(content).hexdigest()

            # Upload to MinIO
            object_key = f"pdfs/{make_object_key(policy_id)}.pdf"
            minio_client.put_object(
                bucket=BUCKET,
                object_name=object_key,
                data=io.BytesIO(content),
                length=len(content),
                content_type="application/pdf",
            )

            # Record success in DB
            return DownloadResult(
                policy_id=policy_id,
                stored_location=object_key,
                http_status=resp.status_code,
                file_size_bytes=len(content),
                content_hash=content_hash,
                error=None,
                attempt_number=attempt,
            )

        except (httpx.HTTPError, Exception) as e:
            if attempt == MAX_RETRIES:
                return DownloadResult(
                    policy_id=policy_id,
                    stored_location=None,
                    http_status=getattr(resp, "status_code", None),
                    error=f"Failed after {MAX_RETRIES} attempts: {str(e)}",
                    attempt_number=attempt,
                )
            delay = BASE_DELAY * (2 ** (attempt - 1))  # exponential backoff
            await asyncio.sleep(delay)
```

**Idempotency**: Before downloading, check if a successful download record exists for that policy_id. If yes, skip.

**After download**: For policies selected for structuring, publish to `stream:structure-tasks`.

### 5.3 Text Extraction (`extractor.py`)

**Goal**: Extract raw text from PDF, store as blob in MinIO.

```python
from pypdf import PdfReader
import io

async def extract_text(policy_id: str, pdf_object_key: str) -> str:
    # Fetch PDF bytes from MinIO
    response = minio_client.get_object(BUCKET, pdf_object_key)
    pdf_bytes = response.read()
    response.close()

    reader = PdfReader(io.BytesIO(pdf_bytes))
    full_text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            full_text += page_text + "\n\n"

    # Store extracted text in MinIO
    text_key = pdf_object_key.replace("pdfs/", "text/").replace(".pdf", ".txt")
    text_bytes = full_text.encode("utf-8")
    minio_client.put_object(
        bucket=BUCKET,
        object_name=text_key,
        data=io.BytesIO(text_bytes),
        length=len(text_bytes),
        content_type="text/plain",
    )

    return full_text, text_key
```

### 5.4 Structuring Pipeline (`structurer.py`)

**Goal**: Use LLM to convert extracted text into the JSON criteria tree.

#### 5.4.1 Initial-Only Selection Logic

```python
def extract_initial_criteria_section(full_text: str) -> str:
    """
    Heuristic to isolate "initial" criteria from the full text.

    Strategy (ordered by priority):
    1. Look for explicit "Initial" section headers:
       - "Initial Medical Necessity Criteria"
       - "Initial Authorization Criteria"
       - "Initial Approval Criteria"
       - "Criteria for Initial..."
    2. If "Initial" AND "Continuation" sections both exist,
       extract only the text between "Initial..." header and "Continuation..." header.
    3. If no explicit "Initial" header but "Continuation" exists,
       extract everything before the "Continuation" section.
    4. If neither exists (e.g., Bariatric Surgery which has only one criteria set),
       extract the first "Criteria for Medically Necessary" section.
    5. Final fallback: send the first 60% of the document text
       (criteria are always before references/codes).
    """
    text = full_text

    # Pattern matching for section boundaries
    initial_patterns = [
        r"(?i)(initial\s+(medical\s+necessity\s+)?criteria)",
        r"(?i)(criteria\s+for\s+initial)",
        r"(?i)(initial\s+authorization)",
        r"(?i)(initial\s+approval)",
    ]
    continuation_patterns = [
        r"(?i)(continuation\s+(medical\s+necessity\s+)?criteria)",
        r"(?i)(criteria\s+for\s+continuation)",
        r"(?i)(continuation\s+of\s+therapy)",
        r"(?i)(re-?authorization\s+criteria)",
    ]
    general_criteria_patterns = [
        r"(?i)(criteria\s+for\s+medically\s+necessary)",
        r"(?i)(medical\s+necessity\s+criteria)",
        r"(?i)(medically\s+necessary\s+when\s+all)",
    ]
    end_markers = [
        r"(?i)(experimental\s+or\s+investigational)",
        r"(?i)(not\s+medically\s+necessary)",
        r"(?i)(CPT\s+codes)",
        r"(?i)(ICD-?10\s+codes)",
        r"(?i)(references)",
        r"(?i)(coding\s+information)",
    ]

    # Implementation: find boundaries, extract section
    # ... (standard regex boundary detection)
    # Return the isolated section text
```

#### 5.4.2 LLM Prompt

```python
# backend/app/llm/prompt.py

SYSTEM_PROMPT = """You are a medical policy analyst that converts insurance clinical guideline criteria 
into structured JSON decision trees.

You will receive the text of an Oscar Health medical clinical guideline. Your task is to extract 
the INITIAL medical necessity criteria and structure them as a JSON tree.

## Rules

1. Extract ONLY the "initial" criteria (not continuation, re-authorization, or revision criteria).
2. If the document has separate "Initial" and "Continuation" sections, use only the Initial section.
3. If there's only one criteria section (no initial/continuation split), use that section.
4. Map hierarchical criteria using AND/OR operators:
   - "ALL of the following" → operator: "AND"
   - "ANY of the following" / "ONE of the following" → operator: "OR"
   - "and" connecting requirements at the same level → AND
   - "or" connecting alternatives → OR
5. Leaf nodes have only rule_id and rule_text (no operator, no rules array).
6. Non-leaf nodes MUST have operator ("AND" or "OR") and rules (array of children).
7. Use hierarchical numbering: "1", "1.1", "1.1.1", etc.
8. Preserve the clinical language exactly as written in the source.
9. Do NOT include CPT/ICD codes, references, or definitions — only the criteria tree.

## Output Format (strict JSON, no markdown)

{
  "title": "Medical Necessity Criteria for [Procedure/Service Name]",
  "insurance_name": "Oscar Health",
  "rules": {
    "rule_id": "1",
    "rule_text": "Description of root criteria requirement",
    "operator": "AND",
    "rules": [
      {
        "rule_id": "1.1",
        "rule_text": "A leaf criterion"
      },
      {
        "rule_id": "1.2",
        "rule_text": "A branch with children",
        "operator": "OR",
        "rules": [
          { "rule_id": "1.2.1", "rule_text": "Child option A" },
          { "rule_id": "1.2.2", "rule_text": "Child option B" }
        ]
      }
    ]
  }
}

## Example

Given criteria text:
"Procedures are considered medically necessary when ALL of the following criteria are met:
1. Informed consent; and
2. Adult aged 18+ with:
   a. BMI ≥40; or
   b. BMI ≥35 with ONE of: sleep apnea, coronary artery disease, diabetes"

Output:
{
  "title": "Medical Necessity Criteria for Bariatric Surgery",
  "insurance_name": "Oscar Health",
  "rules": {
    "rule_id": "1",
    "rule_text": "Procedures are considered medically necessary when ALL of the following criteria are met",
    "operator": "AND",
    "rules": [
      { "rule_id": "1.1", "rule_text": "Informed consent" },
      {
        "rule_id": "1.2",
        "rule_text": "Adult aged 18 years or older with documentation of",
        "operator": "OR",
        "rules": [
          { "rule_id": "1.2.1", "rule_text": "Body mass index (BMI) ≥40" },
          {
            "rule_id": "1.2.2",
            "rule_text": "BMI ≥35 with ONE of the following",
            "operator": "OR",
            "rules": [
              { "rule_id": "1.2.2.1", "rule_text": "Obstructive sleep apnea" },
              { "rule_id": "1.2.2.2", "rule_text": "Coronary artery disease" },
              { "rule_id": "1.2.2.3", "rule_text": "Type 2 diabetes mellitus" }
            ]
          }
        ]
      }
    ]
  }
}

Respond with ONLY the JSON object. No markdown code fences. No explanation."""

USER_PROMPT_TEMPLATE = """Extract the initial medical necessity criteria from this Oscar Health clinical guideline:

---
{extracted_text}
---

Return the structured JSON tree. Remember: initial criteria only, strict JSON, no markdown."""
```

#### 5.4.3 LLM Client

```python
# backend/app/llm/client.py
from openai import AsyncOpenAI
import json

async def structure_criteria(extracted_text: str, model: str = "gpt-4o") -> dict:
    client = AsyncOpenAI()

    response = await client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(extracted_text=extracted_text)},
        ],
        temperature=0.1,  # low temp for deterministic extraction
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    parsed = json.loads(raw)

    metadata = {
        "model": model,
        "prompt_version": "v1",
        "total_tokens": response.usage.total_tokens,
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
    }

    return parsed, metadata
```

#### 5.4.4 Pydantic Validator

```python
# backend/app/llm/validator.py
from pydantic import BaseModel, field_validator
from typing import Optional

class RuleNode(BaseModel):
    rule_id: str
    rule_text: str
    operator: Optional[str] = None  # "AND" | "OR"
    rules: Optional[list["RuleNode"]] = None

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v):
        if v is not None and v not in ("AND", "OR"):
            raise ValueError(f"operator must be 'AND' or 'OR', got '{v}'")
        return v

    @field_validator("rules")
    @classmethod
    def validate_rules_with_operator(cls, v, info):
        if v is not None and len(v) > 0:
            if info.data.get("operator") is None:
                raise ValueError("Non-leaf node with children must have an operator")
        return v

class CriteriaTree(BaseModel):
    title: str
    insurance_name: str
    rules: RuleNode

    @field_validator("insurance_name")
    @classmethod
    def validate_insurance(cls, v):
        if "Oscar" not in v:
            raise ValueError(f"insurance_name should contain 'Oscar', got '{v}'")
        return v

def validate_tree(data: dict) -> tuple[bool, Optional[str]]:
    """Returns (is_valid, error_message)."""
    try:
        CriteriaTree.model_validate(data)
        return True, None
    except Exception as e:
        return False, str(e)
```

### 5.5 Valkey Stream Workers

#### Download Worker

```python
# backend/app/workers/download_worker.py
"""
Consumes from stream:download-tasks, downloads PDFs, publishes to stream:structure-tasks.
Run as: python -m app.workers.download_worker
"""
import asyncio
import valkey

async def run_download_worker():
    r = valkey.from_url(VALKEY_URL)
    consumer_name = f"downloader-{os.getpid()}"

    while True:
        # Read from stream with blocking (5s timeout)
        messages = r.xreadgroup(
            groupname="cg:downloader",
            consumername=consumer_name,
            streams={"stream:download-tasks": ">"},
            count=1,
            block=5000,
        )
        if not messages:
            continue

        for stream, entries in messages:
            for msg_id, data in entries:
                policy_id = data[b"policy_id"].decode()
                pdf_url = data[b"pdf_url"].decode()

                result = await download_pdf(policy_id, pdf_url)
                await save_download_record(result)

                # ACK the message
                r.xack("stream:download-tasks", "cg:downloader", msg_id)

                # Publish event
                r.xadd("stream:events", {
                    "type": "download_complete",
                    "policy_id": policy_id,
                    "success": str(result.error is None),
                })
```

#### Structure Worker

```python
# Similar pattern for structuring — consumes from stream:structure-tasks
# For each task: extract text → isolate initial criteria → call LLM → validate → store
```

### 5.6 API Routes

```python
# backend/app/main.py

# === Pipeline trigger endpoints ===
POST /api/pipeline/discover          # Trigger discovery (returns run_id)
POST /api/pipeline/download          # Trigger download of all undowloaded
POST /api/pipeline/structure         # Trigger structuring of selected 10+
POST /api/pipeline/run-all           # Run full pipeline sequentially

# === Data endpoints (for UI) ===
GET  /api/policies                   # List all policies (paginated, filterable)
GET  /api/policies/{id}              # Single policy detail
GET  /api/policies/{id}/tree         # Get structured criteria tree JSON
GET  /api/policies/{id}/pdf-url      # Get presigned MinIO URL for PDF
GET  /api/policies/{id}/text         # Get extracted text from MinIO

# === Status endpoints ===
GET  /api/pipeline/status            # Current pipeline run status
GET  /api/stats                      # Dashboard stats (total, downloaded, structured)

# === SSE for live updates ===
GET  /api/events                     # Server-Sent Events from Valkey stream:events
```

---

## 6. FRONTEND (React + Vite + Tailwind)

### 6.1 Project Structure

```
frontend/
├── Dockerfile
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   └── client.ts              # Axios/fetch wrapper
│   ├── components/
│   │   ├── Layout.tsx
│   │   ├── PolicyList.tsx         # Left panel: filterable policy list
│   │   ├── PolicyCard.tsx         # Individual policy in the list
│   │   ├── PolicyDetail.tsx       # Right panel: detail view
│   │   ├── CriteriaTree.tsx       # Recursive tree renderer
│   │   ├── TreeNode.tsx           # Single node (leaf or branch)
│   │   ├── OperatorBadge.tsx      # AND/OR visual badge
│   │   ├── PipelineControls.tsx   # Buttons to trigger pipeline stages
│   │   ├── StatusBar.tsx          # Live pipeline status via SSE
│   │   └── SearchFilter.tsx       # Search/filter for policy list
│   ├── hooks/
│   │   ├── usePolicies.ts
│   │   ├── useSSE.ts              # EventSource hook for live updates
│   │   └── useTree.ts
│   └── types/
│       └── index.ts               # TypeScript types matching backend schemas
```

### 6.2 Dockerfile

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
```

### 6.3 Key Components

#### CriteriaTree.tsx — The Core Tree Renderer

```tsx
// Recursive tree component
interface RuleNode {
  rule_id: string;
  rule_text: string;
  operator?: "AND" | "OR";
  rules?: RuleNode[];
}

function TreeNode({ node, depth = 0 }: { node: RuleNode; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 2); // auto-expand first 2 levels
  const isLeaf = !node.rules || node.rules.length === 0;
  const hasChildren = !isLeaf;

  return (
    <div className={`ml-${Math.min(depth * 4, 16)} border-l-2 ${
      node.operator === "AND" ? "border-blue-400" :
      node.operator === "OR" ? "border-amber-400" :
      "border-gray-200"
    } pl-4 py-1`}>
      <div
        className="flex items-start gap-2 cursor-pointer group"
        onClick={() => hasChildren && setExpanded(!expanded)}
      >
        {/* Expand/collapse chevron */}
        {hasChildren && (
          <ChevronIcon expanded={expanded} />
        )}

        {/* Operator badge */}
        {node.operator && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${
            node.operator === "AND"
              ? "bg-blue-100 text-blue-700"
              : "bg-amber-100 text-amber-700"
          }`}>
            {node.operator}
          </span>
        )}

        {/* Leaf indicator */}
        {isLeaf && <span className="text-green-500">●</span>}

        {/* Rule text */}
        <div>
          <span className="text-xs text-gray-400 mr-2">{node.rule_id}</span>
          <span className="text-sm">{node.rule_text}</span>
        </div>
      </div>

      {/* Children (recursive) */}
      {expanded && hasChildren && node.rules.map(child => (
        <TreeNode key={child.rule_id} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}
```

#### PolicyList.tsx — Filterable List

Shows all discovered policies. Each card shows:
- Title
- Guideline code (CG008, etc.)
- Status badge: "PDF Only" (gray) vs "Structured" (green)
- Click to view detail

#### PolicyDetail.tsx — Detail View

When a structured policy is selected:
- Policy title + guideline code
- Link to source PDF (presigned MinIO URL)
- Link to Oscar source page
- The CriteriaTree component rendering the JSON
- "Expand All" / "Collapse All" buttons

---

## 7. ENV FILE

```bash
# .env.example
OPENAI_API_KEY=sk-proj-...
DATABASE_URL=postgresql+asyncpg://oscar:oscar_dev_pw@postgres:5432/oscar_guidelines
VALKEY_URL=valkey://valkey:6379/0
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=oscar-pdfs
MINIO_USE_SSL=false
```

---

## 8. EXECUTION PLAN FOR CLAUDE CODE

### Phase 1: Infrastructure (give to Claude Code first)

**Task**: Set up the project skeleton with Docker Compose and all infrastructure.

```
PROMPT FOR CLAUDE CODE:

Create the following project structure for an Oscar Health medical guidelines scraper:

1. Root: docker-compose.yml with 5 services (valkey, postgres, minio, backend, frontend)
2. backend/: FastAPI project with:
   - Dockerfile (python:3.12-slim + poppler-utils)
   - requirements.txt (see spec)
   - app/config.py, app/db.py, app/models.py (SQLAlchemy async)
   - app/bootstrap.py (MinIO bucket + Valkey stream setup)
   - app/main.py (FastAPI with CORS, health check route)
   - db/init.sql (full schema from spec)
3. frontend/: React + Vite + Tailwind + TypeScript project
   - Dockerfile (node:20-alpine)
   - Basic App.tsx with routing placeholder
4. .env.example with all required vars
5. Root Makefile with: make up, make down, make logs, make reset

Ensure docker-compose up builds and starts all services with health checks.
Do NOT implement pipeline logic yet — just the skeleton.
```

### Phase 2: Discovery + Download Pipeline

**Task**: Implement the scraping and download pipeline.

```
PROMPT FOR CLAUDE CODE:

In the existing backend project, implement:

1. app/pipelines/discoverer.py:
   - Scrape https://www.hioscar.com/clinical-guidelines/medical
   - Try __NEXT_DATA__ JSON first, fall back to link scraping
   - Find ALL guideline PDF URLs
   - Store in policies table with ON CONFLICT DO NOTHING
   - Publish each to Valkey stream:download-tasks

2. app/pipelines/downloader.py:
   - Download PDF from URL with httpx
   - 3 retries, exponential backoff, 0.5s rate limit
   - Upload to MinIO at pdfs/{guideline_code}.pdf
   - Record in downloads table
   - Skip if already downloaded successfully

3. app/minio_client.py: Helper for upload/download/presigned URLs

4. API routes:
   - POST /api/pipeline/discover
   - POST /api/pipeline/download
   - GET /api/stats (count of policies, downloads, structured)

Test: docker-compose up, hit /api/pipeline/discover, then /api/pipeline/download,
verify MinIO has PDFs and DB has records.
```

### Phase 3: LLM Structuring Pipeline

**Task**: Implement text extraction + LLM structuring.

```
PROMPT FOR CLAUDE CODE:

In the existing backend project, implement:

1. app/pipelines/extractor.py:
   - Read PDF from MinIO, extract text with pypdf
   - Store text in MinIO at text/{code}.txt

2. app/llm/prompt.py: System prompt (provided in spec)
3. app/llm/client.py: OpenAI API call with JSON mode, gpt-4o
4. app/llm/validator.py: Pydantic recursive RuleNode/CriteriaTree validator

5. app/pipelines/structurer.py:
   - For a given policy_id: extract text → isolate initial criteria section →
     call LLM → validate → store in structured_policies table
   - initial_only_method heuristic: search for "Initial" headers,
     fall back to first criteria block

6. API route: POST /api/pipeline/structure
   - Accepts optional list of policy_ids, defaults to first 10 CG-prefixed policies
   - Returns structured results

7. API routes:
   - GET /api/policies (list with structured status)
   - GET /api/policies/{id}/tree (return structured_json)

Reference oscar.json in the project root for the expected output shape.
```

### Phase 4: Frontend UI

**Task**: Build the policy browser and tree renderer.

```
PROMPT FOR CLAUDE CODE:

In the existing frontend project, build:

1. Two-panel layout:
   - Left: scrollable policy list with search filter
   - Right: policy detail + criteria tree

2. PolicyList: fetch from GET /api/policies, show title, code,
   status badge (Structured=green, PDF Only=gray)

3. CriteriaTree: recursive component rendering the JSON tree
   - Expand/collapse per node (chevron icon)
   - AND nodes: blue left border + blue badge
   - OR nodes: amber left border + amber badge
   - Leaf nodes: green dot indicator
   - Auto-expand first 2 levels
   - "Expand All" / "Collapse All" buttons

4. PolicyDetail: title, links (PDF + source page), tree

5. PipelineControls: buttons to trigger discover/download/structure
   with loading states

6. Responsive design with Tailwind.

Use Tailwind utility classes only, no component library.
API base URL from VITE_API_URL env var.
```

---

## 9. README TEMPLATE (for final submission)

```markdown
# Oscar Medical Guidelines — PDF Scraper + Criteria Tree Explorer

## Architecture
- **Backend**: FastAPI (Python 3.12) — scraping, LLM structuring, REST API
- **Frontend**: React 18 + Vite + Tailwind CSS — policy browser + tree renderer
- **Database**: PostgreSQL 16 — policies, downloads, structured trees
- **Blob Storage**: MinIO (S3-compatible) — PDFs and extracted text
- **Message Queue**: Valkey (Redis-compatible) — pipeline stage coordination
- **Orchestration**: Docker Compose

## Prerequisites
- Docker & Docker Compose v2
- OpenAI API key (GPT-4o access)

## Setup & Run
\```bash
cp .env.example .env
# Add your OPENAI_API_KEY to .env

docker compose up --build

# Wait for all services to be healthy, then:
# 1. Discover all guidelines
curl -X POST http://localhost:8000/api/pipeline/discover

# 2. Download all PDFs
curl -X POST http://localhost:8000/api/pipeline/download

# 3. Structure 10+ guidelines
curl -X POST http://localhost:8000/api/pipeline/structure

# 4. Open the UI
open http://localhost:5173
\```

## Initial-Only Selection Logic
[See Section 5.4.1 of this spec — copy the explanation there]

The pipeline uses a priority-ordered heuristic:
1. Explicit "Initial" section header detection via regex
2. If both Initial and Continuation exist, boundary extraction
3. If only Continuation exists, everything before it
4. Fallback to first "Criteria for Medically Necessary" section
5. Final fallback: first 60% of document text

This method works reliably for guidelines with clear section structure.
Failure mode: guidelines with unusual formatting may include continuation
criteria. The validation_error field flags these for manual review.

## Which Policies Were Structured
[List the 10+ guideline codes after running, e.g.:]
- CG008 — Bariatric Surgery (Adults)
- CG013 — Acupuncture
- CG018 — Balloon Ostial Dilation
- ... (minimum 10)

## Q&A Notes
- **Discovery completeness**: Checked __NEXT_DATA__ for SSR data,
  verified count against visible page entries
- **Retries/throttling**: 3 retries with exponential backoff,
  0.5s delay between requests
- **Idempotency**: UNIQUE constraint on pdf_url,
  skip-if-exists logic on downloads
- **LLM validation**: Pydantic recursive model, validation_error stored
- **Tree UI**: Recursive React component with expand/collapse,
  AND/OR visual differentiation, auto-expand top 2 levels
```

---

## 10. TIMING STRATEGY

If using this for the actual timed submission (120 min):

| Phase | Time | What's Running |
|-------|------|---------------|
| 0-10  | Docker up, infra verified | You: verify all 5 containers healthy |
| 10-25 | Discovery pipeline | Claude Code: building download pipeline |
| 25-40 | Download all PDFs | Claude Code: building LLM pipeline |
| 40-70 | LLM structuring 10 policies | You: reviewing/fixing LLM output quality |
| 70-100 | Frontend UI | Claude Code: tree component, polish |
| 100-115 | Integration testing | You: full walkthrough, fix broken paths |
| 115-120 | README finalization | You: document which policies, paste Q&A notes |
