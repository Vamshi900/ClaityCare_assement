# Download Module

Downloads all discovered guideline PDFs to local storage.

## How It Works

```
Policies (no download) ──→ httpx GET ──→ SHA-256 hash ──→ Store PDF
                            ↓ fail                        ──→ Record in DB
                         Retry (3x)
                         Backoff + jitter
```

## Retry Strategy

- **3 attempts** per PDF
- **Exponential backoff with jitter**: `2^attempt * random(0.5, 1.5)` seconds
- **0.5s rate limit** between every request (polite scraping)

## Idempotency

Before downloading, queries: `WHERE NOT EXISTS (successful download for this policy)`. Already-downloaded PDFs are skipped.

## Storage

- PDFs stored at `storage/pdfs/{guideline_code}.pdf`
- Each download records: `http_status`, `file_size_bytes`, `content_hash` (SHA-256), `error` (null = success), `attempt_number`

## Key File

`backend/app/pipelines/downloader.py`
