# Extraction Module

Converts guideline PDFs into structured JSON decision trees using a 2-pass LLM pipeline.

This module is **standalone** — it can run as a CLI tool or be imported by the backend.

## Pipeline

```
PDF ──→ Text Extraction ──→ Section Segmentation ──→ LLM Pass 1 ──→ LLM Pass 2 ──→ Validation ──→ JSON Tree
         (pdfplumber)        (3-tier waterfall)      (extract)      (validate)     (schema +
                                                                                   integrity)
```

## Section Segmentation (Initial-Only Selection)

3-tier waterfall to isolate initial criteria:

| Tier | What | Patterns |
|------|------|----------|
| 1 | Explicit "Initial" heading | 5 patterns: `Initial Authorization Criteria`, etc. |
| 2 | Generic criteria bounded by continuation | 4 start + 11 continuation + 7 end markers |
| 3 | Full document fallback | Sends everything, LLM prompt scopes it |

**TOC skip**: If a match produces < 500 chars, it's likely a table-of-contents entry — skip and try the next match.

Method is recorded per policy in `initial_only_method` column.

## 2-Pass LLM Pipeline

**Pass 1 — Extract**: Claude extracts the hierarchical rule tree from the criteria text. System prompt enforces JSON schema, hierarchical numbering, AND/OR operator rules, concise rule_text style.

**Pass 2 — Validate**: Claude cross-references the extraction against source text. Checks for missing rules, extra rules, wrong operators, structural issues. Conservative — only fixes genuine errors.

**JSON retry**: If LLM returns invalid JSON, retries with conversational context explaining the parse error.

## Validation

1. **jsonschema Draft-07** — validates tree structure matches `RuleNode` schema
2. **Deep integrity checks** — parent-child ID consistency, leaf/branch rules, duplicate detection

## Output Schema

```json
{
  "title": "Medical Necessity Criteria for ...",
  "insurance_name": "Oscar Health",
  "rules": {
    "rule_id": "1",
    "rule_text": "...",
    "operator": "AND",
    "rules": [
      { "rule_id": "1.1", "rule_text": "..." },
      { "rule_id": "1.2", "rule_text": "...", "operator": "OR", "rules": [...] }
    ]
  }
}
```

- Leaf nodes: `rule_id` + `rule_text` only
- Non-leaf nodes: `rule_id` + `rule_text` + `operator` (AND/OR) + `rules` array

## CLI Usage

```bash
cd extraction
python extractor.py --pdf policy.pdf --output rules.json
python extractor.py --pdf policy.pdf --output rules.json --validate-against ground_truth.json
python test_extraction.py --dry-run    # No LLM, tests segmentation only
```

## Key Files

| File | Purpose |
|------|---------|
| `segmenter.py` | PDF text extraction + 3-tier section segmentation |
| `prompts.py` | All LLM prompt templates |
| `validator.py` | JSON schema + integrity validation |
| `llm_client.py` | Sync Anthropic client (CLI mode) |
| `extractor.py` | Pipeline orchestrator + CLI entry point |
