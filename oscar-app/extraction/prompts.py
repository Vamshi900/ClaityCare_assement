"""
Prompts — LLM prompt templates for extraction and validation passes.
"""

import json

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
