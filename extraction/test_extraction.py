"""
Test script — runs the extraction pipeline against the Oscar PDF
and validates against the ground truth JSON.

Usage (with API key):
  ANTHROPIC_API_KEY=sk-... python test_extraction.py

Usage (dry run — no LLM, tests segmentation and validation only):
  python test_extraction.py --dry-run
"""

import json
import sys
import argparse
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from extractor import (
    extract_text_from_pdf,
    segment_criteria_section,
    validate_schema,
    validate_rule_tree_integrity,
    compare_with_ground_truth,
    run_pipeline,
    RULE_SCHEMA,
)


PDF_PATH = str(Path(__file__).parent.parent / "full-stack-feb" / "oscar.pdf")
GROUND_TRUTH_PATH = str(Path(__file__).parent.parent / "full-stack-feb" / "oscar.json")


def test_pdf_extraction():
    """Test that we can extract text from the PDF."""
    print("\n=== Test: PDF Text Extraction ===")
    pages = extract_text_from_pdf(PDF_PATH)
    assert len(pages) > 0, "No pages extracted"
    assert any(len(p["text"]) > 100 for p in pages), "Pages have no real text"
    print(f"  ✓ Extracted {len(pages)} pages")
    print(f"  ✓ Total chars: {sum(len(p['text']) for p in pages)}")
    return pages


def test_segmentation(pages):
    """Test that we can find the criteria section."""
    print("\n=== Test: Section Segmentation ===")
    section, method = segment_criteria_section(pages)
    assert len(section) > 500, "Criteria section too short"
    assert "medically necessary" in section.lower(), "Missing key phrase"
    assert "informed consent" in section.lower(), "Missing Rule 1"
    assert "BMI" in section, "Missing BMI criteria"
    assert "psycho-social" in section.lower() or "psychosocial" in section.lower(), \
        "Missing psychosocial section"
    print(f"  ✓ Criteria section: {len(section)} chars")
    print(f"  ✓ Initial-only selection method: {method}")
    print(f"  ✓ Contains key phrases: medically necessary, informed consent, BMI, psychosocial")
    return section


def test_ground_truth_schema():
    """Test that the ground truth JSON itself is valid."""
    print("\n=== Test: Ground Truth Schema Validation ===")
    with open(GROUND_TRUTH_PATH) as f:
        gt = json.load(f)

    errors = validate_schema(gt)
    assert len(errors) == 0, f"Ground truth has schema errors: {errors}"
    print(f"  ✓ Ground truth passes schema validation")

    integrity_errors = validate_rule_tree_integrity(gt["rules"])
    assert len(integrity_errors) == 0, f"Ground truth has integrity errors: {integrity_errors}"
    print(f"  ✓ Ground truth passes integrity validation")

    return gt


def test_ground_truth_completeness(gt):
    """Verify the ground truth has the expected number of rules."""
    print("\n=== Test: Ground Truth Completeness ===")

    def count_rules(node):
        count = 1
        for child in node.get("rules", []):
            count += count_rules(child)
        return count

    total = count_rules(gt["rules"])
    print(f"  ✓ Ground truth has {total} total rules")

    # Check specific expected rules
    def find_rule(node, target_id):
        if node["rule_id"] == target_id:
            return node
        for child in node.get("rules", []):
            found = find_rule(child, target_id)
            if found:
                return found
        return None

    # Verify key rules exist
    expected = {
        "1": ("AND", 5),       # Top level: 5 AND conditions
        "1.2": ("OR", 3),      # Age/BMI: 3 OR options
        "1.2.2": ("OR", 8),    # Comorbidities: 8 OR options
        "1.4": ("AND", 1),     # Pre/post-op plan
        "1.4.1": ("AND", 7),   # Preop eval: 7 AND items
        "1.5": ("AND", 2),     # Psychosocial: 2 AND items
        "1.5.2": ("OR", 3),    # Psych clearance triggers: 3 OR
    }

    for rule_id, (expected_op, expected_children) in expected.items():
        rule = find_rule(gt["rules"], rule_id)
        assert rule is not None, f"Missing rule {rule_id}"
        if expected_op:
            assert rule.get("operator") == expected_op, \
                f"Rule {rule_id}: expected operator {expected_op}, got {rule.get('operator')}"
        if expected_children:
            actual_children = len(rule.get("rules", []))
            assert actual_children == expected_children, \
                f"Rule {rule_id}: expected {expected_children} children, got {actual_children}"
        print(f"  ✓ Rule {rule_id}: operator={expected_op}, children={expected_children}")


def test_self_comparison(gt):
    """Compare ground truth against itself — should be 100% match."""
    print("\n=== Test: Self-Comparison (sanity check) ===")
    report = compare_with_ground_truth(gt, gt)
    assert report["accuracy"] == 100.0, f"Self-comparison not 100%: {report}"
    assert len(report["missing_rules"]) == 0
    assert len(report["extra_rules"]) == 0
    assert len(report["text_mismatches"]) == 0
    assert len(report["operator_mismatches"]) == 0
    print(f"  ✓ Self-comparison: 100% accuracy")


def test_full_pipeline():
    """Run the full pipeline with LLM calls."""
    print("\n=== Test: Full Pipeline (requires ANTHROPIC_API_KEY) ===")
    output = run_pipeline(
        pdf_path=PDF_PATH,
        output_path=str(Path(__file__).parent / "test_output.json"),
        ground_truth_path=GROUND_TRUTH_PATH,
        skip_validation_pass=False,
    )

    gt_report = output["metadata"]["ground_truth_report"]
    if gt_report:
        print(f"\n  Pipeline Results:")
        print(f"  ✓ Accuracy: {gt_report['accuracy']}%")
        print(f"  ✓ Missing rules: {gt_report['missing_rules']}")
        print(f"  ✓ Extra rules: {gt_report['extra_rules']}")
        print(f"  ✓ Text mismatches: {len(gt_report['text_mismatches'])}")
        print(f"  ✓ Operator mismatches: {len(gt_report['operator_mismatches'])}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip LLM calls, test only extraction and validation logic")
    args = parser.parse_args()

    print("=" * 60)
    print("Policy Extraction Engine — Test Suite")
    print("=" * 60)

    # Tests that don't need LLM
    pages = test_pdf_extraction()
    test_segmentation(pages)
    gt = test_ground_truth_schema()
    test_ground_truth_completeness(gt)
    test_self_comparison(gt)

    if not args.dry_run:
        test_full_pipeline()
    else:
        print("\n  [Skipping full pipeline — dry run mode]")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
