# API Reference

FastAPI backend running on port 8000.

## Jobs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs` | Create job (`{"type": "discovery\|download\|structure", "source_url": "..."}`) |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{id}` | Job detail with status and metadata |

## Policies

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/policies` | List all policies (`?search=term`) |
| `GET` | `/api/policies/{id}` | Policy detail (includes `status` field) |
| `GET` | `/api/policies/{id}/tree` | Structured criteria tree (`?version=N`) |
| `GET` | `/api/policies/{id}/text` | Extracted text from PDF |
| `GET` | `/api/policies/{id}/versions` | All extraction versions |
| `GET` | `/api/policies/{id}/pdf-url` | PDF file |
| `POST` | `/api/policies/{id}/extract` | Trigger extraction for one policy |
| `POST` | `/api/policies/{id}/retry` | Retry failed download or extraction |

## Stats

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/stats` | `{total_policies, total_downloaded, total_structured, total_failed_downloads, total_validation_errors}` |
| `GET` | `/health` | Health check |

## Policy Status Values

```
discovered → downloading → downloaded → extracting → extracted → validated
                 ↓                            ↓
           download_failed            extraction_failed
```

## Example Responses

### `GET /api/policies/{id}/tree`
```json
{
  "structured_json": {
    "title": "Medical Necessity Criteria for Bariatric Surgery",
    "insurance_name": "Oscar Health",
    "rules": {
      "rule_id": "1",
      "rule_text": "ALL of the following criteria must be met",
      "operator": "AND",
      "rules": [...]
    }
  },
  "llm_metadata": {"model": "claude-sonnet-4-6", "provider": "anthropic"},
  "validation_error": null,
  "initial_only_method": "first_criteria_section"
}
```

### `GET /api/policies/{id}/versions`
```json
[
  {"version": 2, "is_current": true, "structured_at": "...", "validation_error": null},
  {"version": 1, "is_current": false, "structured_at": "...", "validation_error": "..."}
]
```
