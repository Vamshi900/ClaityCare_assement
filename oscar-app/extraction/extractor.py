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
  python -m extraction.extractor --pdf policy.pdf --output rules.json
  python -m extraction.extractor --pdf policy.pdf --output rules.json --validate-against ground_truth.json
"""

import json
import argparse
import logging
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

from extraction.segmenter import extract_text_from_pdf, segment_criteria_section
from extraction.llm_client import extract_rules_with_llm, validate_and_fix_with_llm, MODEL
from extraction.validator import validate_schema, validate_rule_tree_integrity, compare_with_ground_truth

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ===========================================================================
# Main Pipeline
# ===========================================================================
def _save_intermediate(intermediate_dir: Optional[str], filename: str, data) -> None:
    """Save intermediate result to a file in the intermediate directory."""
    if not intermediate_dir:
        return
    Path(intermediate_dir).mkdir(parents=True, exist_ok=True)
    filepath = Path(intermediate_dir) / filename
    if isinstance(data, str):
        filepath.write_text(data, encoding="utf-8")
    else:
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"  → Intermediate: {filepath}")


def run_pipeline(
    pdf_path: str,
    output_path: str,
    ground_truth_path: Optional[str] = None,
    skip_validation_pass: bool = False,
    insurance_name: str = "Oscar Health",
    intermediate_dir: Optional[str] = None,
) -> dict:
    """
    Full extraction pipeline:
    1. Extract text from PDF
    2. Segment criteria section
    3. LLM extraction
    4. LLM validation
    5. Schema validation
    6. (Optional) Ground truth comparison

    If intermediate_dir is set, each step's output is saved to a file:
      step1_raw_text.txt        — full extracted text per page
      step2_segmented.txt       — criteria section text (initial only)
      step2_metadata.json       — selection method and section stats
      step3_llm_pass1.json      — raw LLM extraction output
      step4_llm_pass2.json      — corrected output + validation report
      step5_schema_check.json   — schema + integrity errors
      step6_gt_comparison.json  — ground truth diff (if provided)
    """
    log.info(f"Starting extraction pipeline for: {pdf_path}")
    if intermediate_dir:
        log.info(f"Intermediate results → {intermediate_dir}")

    # Step 1: Extract text
    pages = extract_text_from_pdf(pdf_path)
    log.info(f"Extracted {len(pages)} pages")
    _save_intermediate(intermediate_dir, "step1_raw_text.txt",
        "\n\n".join(f"=== PAGE {p['page']} ({len(p['text'])} chars) ===\n{p['text']}" for p in pages))

    # Step 2: Segment — extract INITIAL criteria only
    criteria_text, selection_method = segment_criteria_section(pages)
    log.info(f"Initial-only selection method: {selection_method}")
    _save_intermediate(intermediate_dir, "step2_segmented.txt", criteria_text)
    _save_intermediate(intermediate_dir, "step2_metadata.json", {
        "selection_method": selection_method,
        "section_length_chars": len(criteria_text),
        "total_pages": len(pages),
        "total_raw_chars": sum(len(p["text"]) for p in pages),
    })

    # Step 3: LLM extraction
    client = Anthropic()
    extracted = extract_rules_with_llm(client, criteria_text, insurance_name=insurance_name)

    # Pop LLM I/O metadata before saving the clean result
    pass1_input = extracted.pop("_llm_input", None)
    pass1_raw = extracted.pop("_llm_raw_output", None)
    _save_intermediate(intermediate_dir, "step3_llm_pass1.json", {
        "input": pass1_input,
        "output": extracted,
        "raw_llm_response": pass1_raw,
    })

    # Step 4: LLM validation pass
    if not skip_validation_pass:
        # Strip _llm_input from extracted before sending to Pass 2
        corrected, val_report = validate_and_fix_with_llm(
            client, criteria_text, extracted
        )
        log.info(f"Validation report: {json.dumps({k: v for k, v in val_report.items() if k != '_llm_io'}, indent=2)}")
    else:
        corrected = extracted
        val_report = {"skipped": True}

    # Pop LLM I/O from val_report before saving clean metadata
    pass2_io = val_report.pop("_llm_io", None)
    _save_intermediate(intermediate_dir, "step4_llm_pass2.json", {
        "input": pass2_io.get("system") if pass2_io else None,
        "input_messages": pass2_io.get("messages") if pass2_io else None,
        "raw_llm_response": pass2_io.get("raw_output") if pass2_io else None,
        "output": {
            "corrected_rules": corrected,
            "validation_report": val_report,
            "changes_from_pass1": corrected != extracted,
        },
    })

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
    _save_intermediate(intermediate_dir, "step5_schema_check.json", {
        "schema_errors": schema_errors,
        "integrity_errors": integrity_errors,
        "total_errors": len(all_errors),
        "passed": len(all_errors) == 0,
    })

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
        _save_intermediate(intermediate_dir, "step6_gt_comparison.json", gt_report)

    # Save final output
    output = {
        "extracted_rules": corrected,
        "metadata": {
            "source_pdf": pdf_path,
            "pages_processed": len(pages),
            "criteria_section_length": len(criteria_text),
            "initial_only_method": selection_method,
            "model": MODEL,
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
    parser.add_argument(
        "--intermediate-dir",
        help="Directory to save intermediate results from each pipeline step",
    )

    args = parser.parse_args()
    run_pipeline(
        pdf_path=args.pdf,
        output_path=args.output,
        ground_truth_path=args.validate_against,
        skip_validation_pass=args.skip_llm_validation,
        insurance_name=args.insurance_name,
        intermediate_dir=args.intermediate_dir,
    )


if __name__ == "__main__":
    main()
