# Policy Rule Extraction Engine

Converts insurance clinical guideline PDFs (like Oscar's Bariatric Surgery policy) into structured JSON rule trees using a multi-pass LLM pipeline.

## The Problem

Insurance policies define medical necessity criteria as deeply nested conditional logic buried in PDF documents. For example:

> Procedures are considered medically necessary when **ALL** of the following criteria are met:
> 1. Informed consent; **and**
> 2. Adult aged 18+ with **ONE** of:
>    a. BMI ≥40; **or**
>    b. BMI ≥35 with **ONE** of 8 comorbidities; **or**
>    c. BMI ≥30-34.9
> 3. Failure of non-surgical therapy; **and**
> ...

This engine converts that into a machine-readable rule tree:

```json
{
  "rule_id": "1",
  "rule_text": "Procedures are considered medically necessary when ALL of the following criteria are met",
  "operator": "AND",
  "rules": [
    { "rule_id": "1.1", "rule_text": "Informed consent..." },
    { "rule_id": "1.2", "operator": "OR", "rules": [...] },
    ...
  ]
}
```

## Architecture

```
PDF → Text Extraction → Section Segmentation → LLM Pass 1 (Extract) → LLM Pass 2 (Validate) → Schema Check → Output
```

| Stage | What it does | Why it exists |
|-------|-------------|---------------|
| **Text Extraction** | `pdftotext -layout` (fallback: pdfplumber) | Preserves word spacing and layout |
| **Segmentation** | Regex finds "Criteria for Medically Necessary" section | Avoids feeding 20 pages of billing codes to the LLM |
| **LLM Pass 1** | Claude extracts hierarchical rule tree | Core extraction with detailed schema instructions |
| **LLM Pass 2** | Claude validates Pass 1 against source text | Catches missing rules, wrong AND/OR operators |
| **Schema Check** | jsonschema + custom integrity checks | Ensures valid structure before downstream use |
| **GT Comparison** | Diff against human-curated ground truth | Measures accuracy (optional) |

## Usage

```bash
# Install
pip install -r requirements.txt

# Full pipeline
ANTHROPIC_API_KEY=sk-... python extractor.py \
  --pdf oscar.pdf \
  --output rules.json

# With ground truth validation
ANTHROPIC_API_KEY=sk-... python extractor.py \
  --pdf oscar.pdf \
  --output rules.json \
  --validate-against oscar_ground_truth.json

# Dry-run tests (no LLM)
python test_extraction.py --dry-run
```

## How the PDF Maps to JSON

See `ARCHITECTURE.py` for the full mapping table. The key insight is reading **conjunctions**:

| PDF Signal | JSON Operator |
|-----------|---------------|
| "when ALL of the following criteria are met" | `AND` at that level |
| "with ONE of the following" | `OR` at that level |
| Items ending with "; and" | Siblings joined by `AND` |
| Items ending with "; or" | Siblings joined by `OR` |

## Prompt Design

The extraction prompt has 6 explicit rules targeting observed failure modes:

1. **Hierarchical numbering** — prevents flat IDs
2. **AND/OR detection** — teaches signal words
3. **Text fidelity** — prevents paraphrasing clinical terms
4. **Completeness** — forces all list items (the 8 comorbidities under BMI ≥35)
5. **Scope control** — excludes revision/experimental sections
6. **Structural signals** — the conjunction-reading rules above

## Validation

Three layers:
1. **LLM self-check** — second Claude call cross-references extraction against source
2. **JSON Schema** — structural conformance
3. **Integrity checks** — parent-child ID consistency, leaf/branch node rules, no duplicates

## Files

| File | Purpose |
|------|---------|
| `extractor.py` | Main pipeline — all 6 stages |
| `ARCHITECTURE.py` | Design decisions, prompt rationale, PDF→JSON mapping |
| `test_extraction.py` | Test suite (dry-run + full pipeline) |
| `requirements.txt` | Python dependencies |
