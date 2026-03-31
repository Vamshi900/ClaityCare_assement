"""
Validator — JSON schema validation and ground truth comparison.
"""

import logging

import jsonschema

log = logging.getLogger(__name__)

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
