# ClarityCare Assessment

## Project Overview
Full-stack assessment: Oscar Medical Guidelines PDF Scraper + "Initial Criteria" Tree Explorer.

### What It Does
1. **PDF Discovery** - Scrapes all medical guideline PDF links from Oscar's clinical guidelines page
2. **PDF Download** - Downloads all discovered PDFs with retry/rate-limiting
3. **Structuring Pipeline** - Uses LLM to extract initial medical necessity criteria into JSON decision trees (at least 10)
4. **UI** - Browse policies and navigate/render criteria trees with expand/collapse

### Source
- Guidelines page: https://www.hioscar.com/clinical-guidelines/medical
- Example policy: https://www.hioscar.com/medical/cg013v11

## Tech Stack
TBD - to be updated once implementation begins.

## Data Model
- **Policies** - title, pdf_url (unique), source_page_url, discovered_at
- **Downloads** - policy_id, stored_location, downloaded_at, http_status, error
- **Structured Policies** - policy_id, extracted_text, structured_json, structured_at, llm_metadata, validation_error

## JSON Schema
Matches `full-stack-feb/oscar.json`:
- Top level: title, insurance_name ("Oscar Health"), rules (root node)
- Rules node: rule_id, rule_text, optional operator (AND/OR), optional rules[]
- Leaf nodes: rule_id + rule_text only
- Non-leaf nodes: include operator + rules[]

## Key Constraints
- **Initial criteria only** - Must extract initial (not continuation) criteria
- **Idempotent reruns** - Discovery/download must not create duplicates
- **Polite scraping** - Throttling and retries required
- **At least 10** structured trees required

## Commands
TBD - to be updated once implementation begins.

## Development Guidelines
- Keep `.env.example` with placeholder secrets (never commit real keys)
- Store LLM metadata (model name, prompt) with structured output
- Validate LLM JSON output against required schema
- Log and persist errors visibly
