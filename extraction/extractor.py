"""
Policy Rule Extraction Engine
==============================
Converts insurance clinical guideline PDFs into structured JSON rule trees
using a multi-pass LLM pipeline with validation.

Architecture:
  1. PDF Text Extraction (pdfplumber)
  2. Section Segmentation (regex + heuristics)
  3. LLM Pass 1: Rule Tree Extraction (structured output)
  4. LLM Pass 2: Validation & Gap-Fill
  5. Schema Validation (jsonschema)
  6. Human-in-the-loop diff review

Usage:
  python extractor.py --pdf policy.pdf --output rules.json
  python extractor.py --pdf policy.pdf --output rules.json --validate-against ground_truth.json
"""

import json
import re
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional

import pdfplumber
from anthropic import Anthropic
import jsonschema

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL = "claude-opus-4-20250514"
MAX_TOKENS = 8192

# JSON Schema that every extracted rule tree must conform to
RULE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "InsurancePolicyRules",
    "type": "object",
    "required": ["title", "insurance_name", "rules"],
    "properties": {
        "title": {"type": "string"},
        "insurance_name": {"type": "string"},
        "rules": {"$ref": "#/$defs/RuleNode"},
    },
    "$defs": {
        "RuleNode": {
            "type": "object",
            "required": ["rule_id", "rule_text"],
            "properties": {
                "rule_id": {"type": "string"},
                "rule_text": {"type": "string"},
                "operator": {"type": "string", "enum": ["AND", "OR"]},
                "rules": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/RuleNode"},
                },
            },
            "additionalProperties": False,
        }
    },
}


# ===========================================================================
# STEP 1: PDF Text Extraction
# ===========================================================================
def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """
    Extract text page-by-page using multiple strategies.
    Strategy 1: pdftotext (poppler) — best for preserving word spacing.
    Strategy 2: pdfplumber — fallback if pdftotext unavailable.
    Returns list of {"page": int, "text": str}.
    """
    import subprocess

    pages = []

    # Try pdftotext first (better word spacing)
    try:
        # Get page count
        info = subprocess.run(
            ["pdfinfo", pdf_path], capture_output=True, text=True, check=True
        )
        page_count = 0
        for line in info.stdout.split("\n"):
            if line.startswith("Pages:"):
                page_count = int(line.split(":")[1].strip())
                break

        for i in range(1, page_count + 1):
            result = subprocess.run(
                ["pdftotext", "-f", str(i), "-l", str(i), "-layout", pdf_path, "-"],
                capture_output=True, text=True, check=True,
            )
            text = result.stdout
            pages.append({"page": i, "text": text})
            log.info(f"Extracted page {i} (pdftotext): {len(text)} chars")

        if pages:
            return pages
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning(f"pdftotext failed, falling back to pdfplumber: {e}")

    # Fallback: pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page": i, "text": text})
            log.info(f"Extracted page {i} (pdfplumber): {len(text)} chars")
    return pages


# ===========================================================================
# STEP 2: Section Segmentation
# ===========================================================================
# We target the "Criteria for Medically Necessary Procedures" section
# because that's where the rule tree lives in bariatric surgery guidelines.
# The regex patterns below are tuned for Oscar-style clinical guidelines
# but are generalizable.

SECTION_PATTERNS = {
    "criteria": [
        r"Criteria\s+for\s+Medically\s+Necessary",
        r"Medical\s+Necessity\s+Criteria",
        r"Clinical\s+Indications",
        r"Procedures?\s+(?:are|is)\s+considered\s+medically\s+necessary\s+when",
    ],
    "end_markers": [
        r"Experimental\s+or\s+Investigational",
        r"Not\s+Medically\s+Necessary",
        r"Applicable\s+Billing\s+Codes",
        r"Repair,\s+Replacement",
        r"Relative\s+Contraindications",
    ],
}


def segment_criteria_section(pages: list[dict]) -> str:
    """
    Pull out just the medical necessity criteria section from the full text.
    Falls back to full document if section markers aren't found.
    """
    full_text = "\n\n".join(
        f"--- PAGE {p['page']} ---\n{p['text']}" for p in pages
    )

    # Find start of criteria section
    start_idx = 0
    for pattern in SECTION_PATTERNS["criteria"]:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            # Back up to the start of the line
            start_idx = full_text.rfind("\n", 0, match.start()) + 1
            log.info(f"Found criteria section start at char {start_idx} via pattern: {pattern}")
            break

    # Find end of criteria section
    end_idx = len(full_text)
    for pattern in SECTION_PATTERNS["end_markers"]:
        match = re.search(pattern, full_text[start_idx:], re.IGNORECASE)
        if match:
            candidate = start_idx + match.start()
            if candidate < end_idx and candidate > start_idx + 200:
                end_idx = candidate
                log.info(f"Found criteria section end at char {end_idx} via pattern: {pattern}")

    section = full_text[start_idx:end_idx].strip()
    log.info(f"Extracted criteria section: {len(section)} chars")
    return section


# ===========================================================================
# STEP 3: LLM Pass 1 — Rule Tree Extraction
# ===========================================================================
EXTRACTION_SYSTEM_PROMPT = """\
You are an expert at converting insurance clinical guideline documents into \
structured JSON rule trees.

Your task: Given the "medical necessity criteria" section of a clinical \
guideline PDF, produce a JSON object that captures EVERY rule, sub-rule, \
and condition as a nested tree.

## Output Schema

```json
{{
  "title": "<descriptive title of the policy>",
  "insurance_name": "{insurance_name}",
  "rules": {{
    "rule_id": "1",
    "rule_text": "<top-level rule text>",
    "operator": "AND" | "OR",
    "rules": [
      {{
        "rule_id": "1.1",
        "rule_text": "...",
        // If this rule has sub-conditions:
        "operator": "AND" | "OR",
        "rules": [...]
      }}
    ]
  }}
}}
```

## CRITICAL RULES for extraction:

1. **Numbering**: Use hierarchical dot-notation with ONLY numeric segments \
(1, 1.1, 1.1.1, 1.1.1.1, etc.)
   - The top-level "rules" node is always rule_id "1"
   - Direct children are 1.1, 1.2, 1.3, ...
   - Their children are 1.1.1, 1.1.2, etc.
   - NEVER use non-numeric IDs like "1.2.2.comorbidities" or "1.2.2.0"

2. **Operators**:
   - "AND" when ALL sub-rules must be satisfied (signaled by "and", "all of \
the following", semicolons separating items joined by "and")
   - "OR" when ANY sub-rule suffices (signaled by "or", "one of the following", \
"any of the following")
   - Only include "operator" and "rules" when there ARE sub-conditions
   - Leaf nodes have NO "operator" and NO "rules" array

3. **rule_text style**: Use the CONCISE heading with key parenthetical \
details — the short descriptor with its parenthetical list, but NOT \
long explanatory clauses after dashes or "to" phrases. Guidelines:
   - GOOD: "Laboratory testing (blood glucose, lipid panel, CBC, metabolic panel)"
   - BAD: "Fasting blood glucose, fasting lipid panel, complete blood count (CBC)..." (expanded form)
   - ALSO BAD: "Laboratory testing" (too short when a parenthetical list exists in the source)
   - GOOD: "Cardiopulmonary risk evaluation"
   - BAD: "Cardiopulmonary risk evaluation - to assess as part of standard pre-operative clearance with EKG..."
   - GOOD: "Behavioral evaluation"
   - BAD: "Behavioral evaluation to determine ability to succeed and adhere to recommendations..."
   Rule: Keep the heading + parenthetical list if one exists in the source. \
Drop everything after a dash " - " or long "to [verb]" explanatory clause. \
Keep short reference notes (e.g., ", see section below"). \
Strip trailing colons and semicolons. Do NOT include trailing ":" or \
";" or "; and" or "; or".

4. **Text fidelity**: Preserve the original clinical terminology. Do NOT \
paraphrase medical terms. Keep abbreviations and parenthetical \
clarifications. But DO trim to the concise heading as described above.

5. **Completeness**: Capture EVERY numbered/lettered item. If the document \
lists items i through viii, all eight must appear as direct children.

6. **Flat structure for lists**: When a rule says "with ONE of the following" \
or "ALL of the following" followed by a list of items, those items should \
be DIRECT children of that rule. Do NOT create intermediate grouping or \
wrapper nodes.

7. **Scope**: Only extract the INITIAL medical necessity criteria for the \
primary procedure/treatment. Do NOT include:
   - Continuation/maintenance criteria (unless no initial criteria exist)
   - Revision/conversion/repair criteria
   - Experimental or investigational sections
   - Billing codes, definitions, or references

8. **Structural signals to watch for**:
   - "when ALL of the following criteria are met" → AND at that level
   - "with ONE of the following" → OR at that level
   - "; and" at end of items → AND connecting siblings
   - "; or" at end of items → OR connecting siblings
   - Numbered lists (1, 2, 3) with "and" → AND
   - Lettered sub-items (a, b, c) with "or" → OR

Set insurance_name to "{insurance_name}".
Return ONLY valid JSON. No markdown fences, no commentary.\
"""


EXTRACTION_USER_PROMPT = """\
Here is the medical necessity criteria section extracted from the PDF:

<criteria_text>
{criteria_text}
</criteria_text>

Here is an example of the EXACT output format and style expected:

<example_output>
{example_json}
</example_output>

Convert the criteria text into the structured JSON rule tree. Follow the \
example's style exactly:
- Concise rule_text (headings with parenthetical details, not full paragraphs)
- No trailing colons or semicolons in rule_text
- Flat children under OR/AND nodes (no intermediate wrapper nodes)
- Hierarchical numeric-only rule_ids (1, 1.1, 1.1.1, ...)
- Leaf nodes must NOT have "operator" or "rules" keys
- Return ONLY valid JSON\
"""


EXAMPLE_JSON = json.dumps({
    "title": "Medical Necessity Criteria for [Procedure Name]",
    "insurance_name": "[Insurance Company]",
    "rules": {
        "rule_id": "1",
        "rule_text": "Procedures are considered medically necessary when ALL of the following criteria are met",
        "operator": "AND",
        "rules": [
            {"rule_id": "1.1", "rule_text": "Informed consent with appropriate explanation of risks, benefits, and alternatives"},
            {
                "rule_id": "1.2", "rule_text": "Patient meets age and clinical requirements with documentation of",
                "operator": "OR",
                "rules": [
                    {"rule_id": "1.2.1", "rule_text": "Primary clinical threshold met"},
                    {
                        "rule_id": "1.2.2", "rule_text": "Secondary threshold with ONE of the following comorbidities",
                        "operator": "OR",
                        "rules": [
                            {"rule_id": "1.2.2.1", "rule_text": "Comorbidity A (e.g. specific clinical condition)"},
                            {"rule_id": "1.2.2.2", "rule_text": "Comorbidity B, objectively documented"},
                            {"rule_id": "1.2.2.3", "rule_text": "Comorbidity C"},
                        ]
                    },
                ]
            },
            {"rule_id": "1.3", "rule_text": "Failure of conservative/non-surgical therapy"},
            {
                "rule_id": "1.4", "rule_text": "Comprehensive evaluation plan",
                "operator": "AND",
                "rules": [
                    {"rule_id": "1.4.1", "rule_text": "Laboratory testing (specific tests listed)"},
                    {"rule_id": "1.4.2", "rule_text": "Specialist evaluation"},
                ]
            },
        ]
    }
}, indent=2)


def extract_rules_with_llm(
    client: Anthropic,
    criteria_text: str,
    insurance_name: str = "Oscar Health",
) -> dict:
    """
    LLM Pass 1: Extract the rule tree from the criteria section.
    """
    log.info("LLM Pass 1: Extracting rule tree...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=EXTRACTION_SYSTEM_PROMPT.format(insurance_name=insurance_name),
        messages=[
            {
                "role": "user",
                "content": EXTRACTION_USER_PROMPT.format(
                    criteria_text=criteria_text,
                    example_json=EXAMPLE_JSON,
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown fences if model included them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse LLM output as JSON: {e}")
        log.error(f"Raw output (first 500 chars): {raw[:500]}")
        raise

    log.info(f"Pass 1 complete. Top-level keys: {list(result.keys())}")
    return result


# ===========================================================================
# STEP 4: LLM Pass 2 — Validation & Gap-Fill
# ===========================================================================
VALIDATION_SYSTEM_PROMPT = """\
You are a QA specialist for structured insurance policy data. You will \
receive two inputs:
1. The original criteria text from the PDF
2. A JSON rule tree that was extracted from that text

## YOUR JOB — MINIMAL, CONSERVATIVE corrections only:

A) Find rules in the source text that are MISSING from the JSON → add them
B) Find rules in the JSON that do NOT exist in the source text → remove them
C) Check AND/OR operators match the logical connectives in the source text
D) Verify rule_id uses numeric-only dot-notation (1, 1.1, 1.2.3 — never \
   text IDs like "1.2.comorbidities")
E) Verify leaf nodes don't have "operator" or "rules" keys
F) Verify non-leaf nodes have both "operator" and "rules" keys

## CRITICAL CONSTRAINTS:

- DO NOT restructure or reorganize the tree. If the extraction has items \
as flat children of a node, keep them flat. Never add intermediate \
grouping/wrapper nodes.
- DO NOT expand or lengthen rule_text. The extraction intentionally uses \
concise headings (e.g., "GI evaluation" instead of "GI evaluation - H. pylori \
screening in high-risk populations..."). This is CORRECT. Do not add back \
explanatory clauses, dashes, or elaborations from the source text.
- DO NOT change rule_text unless it contains a factually wrong medical term \
or completely misidentifies the rule. Concise summaries are intentional.
- DO NOT split a single node into multiple nodes or merge multiple nodes.
- DO NOT change an operator unless the source text clearly indicates \
a different logical connective.
- When in doubt, KEEP the original extraction unchanged.
- Preserve the insurance_name exactly as given.

Return a corrected JSON rule tree that fixes ONLY genuine errors. If the \
original extraction was correct, return it unchanged.

Return your response as JSON with two keys:
{
  "corrected_rules": { ... the full corrected rule tree ... },
  "validation_report": {
    "issues_found": [ "description of issue 1", ... ],
    "rules_added": [ "rule_id of any added rules" ],
    "rules_modified": [ "rule_id of any modified rules" ],
    "operators_changed": [ "rule_id where operator was corrected" ],
    "is_valid": true/false
  }
}

Return ONLY valid JSON. No markdown fences.\
"""


VALIDATION_USER_PROMPT = """\
<original_criteria_text>
{criteria_text}
</original_criteria_text>

<extracted_json>
{extracted_json}
</extracted_json>

Validate and correct the extracted JSON. Return the corrected rule tree \
and validation report as specified.\
"""


def validate_and_fix_with_llm(
    client: Anthropic,
    criteria_text: str,
    extracted: dict,
) -> tuple[dict, dict]:
    """
    LLM Pass 2: Validate the extraction against the source text
    and fix any gaps or errors.

    Returns (corrected_rules, validation_report).
    """
    log.info("LLM Pass 2: Validating extraction...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=VALIDATION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": VALIDATION_USER_PROMPT.format(
                    criteria_text=criteria_text,
                    extracted_json=json.dumps(extracted, indent=2),
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"Validation pass failed to parse: {e}")
        log.error(f"Raw output (first 500 chars): {raw[:500]}")
        # Fall back to original extraction
        return extracted, {"issues_found": ["Validation pass failed"], "is_valid": False}

    corrected = result.get("corrected_rules", extracted)
    report = result.get("validation_report", {})

    issues = report.get("issues_found", [])
    log.info(f"Pass 2 complete. Issues found: {len(issues)}")
    for issue in issues:
        log.warning(f"  - {issue}")

    return corrected, report


# ===========================================================================
# STEP 5: Schema Validation
# ===========================================================================
def validate_schema(rules: dict) -> list[str]:
    """
    Validate the rule tree against the JSON Schema.
    Returns list of validation errors (empty = valid).
    """
    errors = []
    validator = jsonschema.Draft7Validator(RULE_SCHEMA)
    for error in sorted(validator.iter_errors(rules), key=str):
        errors.append(f"{error.json_path}: {error.message}")

    if errors:
        log.warning(f"Schema validation found {len(errors)} errors")
        for e in errors:
            log.warning(f"  - {e}")
    else:
        log.info("Schema validation passed ✓")

    return errors


def validate_rule_tree_integrity(node: dict, path: str = "") -> list[str]:
    """
    Deep structural checks beyond what JSON Schema catches:
    - Leaf nodes must not have 'operator' or 'rules'
    - Non-leaf nodes must have both 'operator' and 'rules'
    - rule_id must be hierarchically consistent with parent
    - No duplicate rule_ids
    """
    errors = []
    rule_id = node.get("rule_id", "?")

    has_children = "rules" in node and isinstance(node.get("rules"), list)
    has_operator = "operator" in node

    if has_children and not has_operator:
        errors.append(f"Rule {rule_id}: has 'rules' array but no 'operator'")

    if has_operator and not has_children:
        errors.append(f"Rule {rule_id}: has 'operator' but no 'rules' array")

    if has_children:
        child_ids = set()
        for child in node["rules"]:
            child_id = child.get("rule_id", "?")

            # Check parent-child id consistency
            if path and not child_id.startswith(rule_id + "."):
                errors.append(
                    f"Rule {child_id}: should start with '{rule_id}.' (parent is {rule_id})"
                )

            # Check duplicates
            if child_id in child_ids:
                errors.append(f"Duplicate rule_id: {child_id}")
            child_ids.add(child_id)

            # Recurse
            errors.extend(validate_rule_tree_integrity(child, rule_id))

    return errors


# ===========================================================================
# STEP 6: Ground Truth Comparison (optional)
# ===========================================================================
def compare_with_ground_truth(extracted: dict, ground_truth: dict) -> dict:
    """
    Compare extracted rules against a ground truth JSON.
    Returns a diff report.
    """

    def flatten_rules(node: dict, result: dict = None) -> dict:
        if result is None:
            result = {}
        rule_id = node.get("rule_id", "")
        result[rule_id] = {
            "text": node.get("rule_text", ""),
            "operator": node.get("operator"),
            "num_children": len(node.get("rules", [])),
        }
        for child in node.get("rules", []):
            flatten_rules(child, result)
        return result

    extracted_flat = flatten_rules(extracted.get("rules", extracted))
    truth_flat = flatten_rules(ground_truth.get("rules", ground_truth))

    report = {
        "missing_rules": [],      # In ground truth but not in extracted
        "extra_rules": [],        # In extracted but not in ground truth
        "text_mismatches": [],    # Same rule_id but different text
        "operator_mismatches": [],
        "total_ground_truth": len(truth_flat),
        "total_extracted": len(extracted_flat),
    }

    def normalize_text(s: str) -> str:
        """Normalize text for comparison: whitespace, trailing punctuation."""
        s = " ".join(s.split())
        s = s.rstrip(":;, ")
        return s

    for rule_id, truth in truth_flat.items():
        if rule_id not in extracted_flat:
            report["missing_rules"].append(rule_id)
        else:
            ext = extracted_flat[rule_id]
            t_text = normalize_text(truth["text"])
            e_text = normalize_text(ext["text"])
            # Allow prefix match: if extracted starts with GT text, it's
            # just more detailed — not a mismatch
            if t_text != e_text and not e_text.startswith(t_text):
                report["text_mismatches"].append({
                    "rule_id": rule_id,
                    "expected": t_text[:120],
                    "got": e_text[:120],
                })
            if truth["operator"] != ext["operator"]:
                report["operator_mismatches"].append({
                    "rule_id": rule_id,
                    "expected": truth["operator"],
                    "got": ext["operator"],
                })

    for rule_id in extracted_flat:
        if rule_id not in truth_flat:
            report["extra_rules"].append(rule_id)

    # Compute accuracy
    matched = (
        report["total_ground_truth"]
        - len(report["missing_rules"])
        - len(report["text_mismatches"])
        - len(report["operator_mismatches"])
    )
    report["accuracy"] = round(matched / max(report["total_ground_truth"], 1) * 100, 1)

    return report


# ===========================================================================
# Main Pipeline
# ===========================================================================
def run_pipeline(
    pdf_path: str,
    output_path: str,
    ground_truth_path: Optional[str] = None,
    skip_validation_pass: bool = False,
    insurance_name: str = "Oscar Health",
) -> dict:
    """
    Full extraction pipeline:
    1. Extract text from PDF
    2. Segment criteria section
    3. LLM extraction
    4. LLM validation
    5. Schema validation
    6. (Optional) Ground truth comparison
    """
    log.info(f"Starting extraction pipeline for: {pdf_path}")

    # Step 1: Extract text
    pages = extract_text_from_pdf(pdf_path)
    log.info(f"Extracted {len(pages)} pages")

    # Step 2: Segment
    criteria_text = segment_criteria_section(pages)

    # Step 3: LLM extraction
    client = Anthropic()
    extracted = extract_rules_with_llm(client, criteria_text, insurance_name=insurance_name)

    # Step 4: LLM validation pass
    if not skip_validation_pass:
        corrected, val_report = validate_and_fix_with_llm(
            client, criteria_text, extracted
        )
        log.info(f"Validation report: {json.dumps(val_report, indent=2)}")
    else:
        corrected = extracted
        val_report = {"skipped": True}

    # Step 5: Schema validation
    schema_errors = validate_schema(corrected)
    integrity_errors = validate_rule_tree_integrity(
        corrected.get("rules", corrected)
    )

    all_errors = schema_errors + integrity_errors
    if all_errors:
        log.warning(f"Total validation errors: {len(all_errors)}")
    else:
        log.info("All validation checks passed ✓")

    # Step 6: Ground truth comparison
    gt_report = None
    if ground_truth_path:
        with open(ground_truth_path) as f:
            ground_truth = json.load(f)
        gt_report = compare_with_ground_truth(corrected, ground_truth)
        log.info(f"Ground truth accuracy: {gt_report['accuracy']}%")
        log.info(f"Missing rules: {gt_report['missing_rules']}")
        log.info(f"Extra rules: {gt_report['extra_rules']}")
        log.info(f"Text mismatches: {len(gt_report['text_mismatches'])}")
        log.info(f"Operator mismatches: {len(gt_report['operator_mismatches'])}")

    # Save output
    output = {
        "extracted_rules": corrected,
        "metadata": {
            "source_pdf": pdf_path,
            "pages_processed": len(pages),
            "criteria_section_length": len(criteria_text),
            "schema_errors": schema_errors,
            "integrity_errors": integrity_errors,
            "validation_report": val_report,
            "ground_truth_report": gt_report,
        },
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    log.info(f"Output saved to {output_path}")

    return output


# ===========================================================================
# CLI
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Extract structured rules from insurance policy PDFs"
    )
    parser.add_argument("--pdf", required=True, help="Path to the policy PDF")
    parser.add_argument("--output", required=True, help="Path for output JSON")
    parser.add_argument(
        "--validate-against",
        help="Path to ground truth JSON for comparison",
    )
    parser.add_argument(
        "--skip-llm-validation",
        action="store_true",
        help="Skip the second LLM validation pass",
    )
    parser.add_argument(
        "--insurance-name",
        default="Oscar Health",
        help="Name of the insurance company (default: Oscar Health)",
    )

    args = parser.parse_args()
    run_pipeline(
        pdf_path=args.pdf,
        output_path=args.output,
        ground_truth_path=args.validate_against,
        skip_validation_pass=args.skip_llm_validation,
        insurance_name=args.insurance_name,
    )


if __name__ == "__main__":
    main()
