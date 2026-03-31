# Discovery Module

Scrapes Oscar Health's clinical guidelines page to find all medical guideline PDF links.

## How It Works

```
Source URL (any) ──→ Fetch HTML ──→ Strategy 1: __NEXT_DATA__ JSON
                                  ──→ Strategy 2: <a> tag scraping
                                  ──→ Strategy 3: Visit pages for PDF URLs
                                  ──→ Store in DB (ON CONFLICT DO NOTHING)
```

## Strategies (tried in order)

1. **`__NEXT_DATA__` extraction** — Oscar uses Next.js. The page embeds all data in a JSON blob inside `<script id="__NEXT_DATA__">`. We parse this to get every guideline entry.

2. **HTML `<a>` tag scraping** — If `__NEXT_DATA__` is missing, scrape all links matching:
   - `ctfassets.net/*.pdf` (direct PDF links)
   - `/medical/cg013v11` (guideline page links)

3. **Page visiting** — For guideline page links (not direct PDFs), visit each page with 0.5s throttling to find the actual PDF URL.

## Idempotency

`INSERT INTO policies ... ON CONFLICT (pdf_url) DO NOTHING` — running discovery twice produces zero duplicates.

## Custom URLs

The discovery module accepts any source URL, not just Oscar's:
```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"type": "discovery", "source_url": "https://example.com/guidelines"}'
```

## Key File

`backend/app/pipelines/discoverer.py`
