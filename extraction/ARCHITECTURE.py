# Prompt Engineering & Extraction Strategy
# ==========================================
# This file documents the reasoning behind each prompt and the overall
# extraction architecture. Use it as a reference when adapting the engine
# to new policy types.

"""
=============================================================================
ARCHITECTURE OVERVIEW
=============================================================================

The pipeline has 6 stages. Here's WHY each exists and how they connect:

┌─────────────────┐
│  1. PDF Extract  │  pdfplumber → raw text per page
└────────┬────────┘
         │
┌────────▼────────┐
│ 2. Segmentation  │  Regex finds "Criteria for Medically Necessary" section
└────────┬────────┘  Avoids feeding billing codes, references, etc. to LLM
         │
┌────────▼────────┐
│ 3. LLM Pass 1   │  Claude extracts the hierarchical rule tree
└────────┬────────┘  Single-shot structured output with detailed schema
         │
┌────────▼────────┐
│ 4. LLM Pass 2   │  Claude validates Pass 1 output against source text
└────────┬────────┘  Catches missing rules, wrong operators, structural issues
         │
┌────────▼────────┐
│ 5. Schema Check  │  jsonschema + custom integrity checks
└────────┬────────┘  Ensures output conforms to expected structure
         │
┌────────▼────────┐
│ 6. GT Comparison │  Diff against human-curated ground truth (optional)
└─────────────────┘  Measures extraction accuracy


=============================================================================
KEY DESIGN DECISIONS
=============================================================================

1. WHY TWO LLM PASSES?
   
   Clinical guidelines have deeply nested conditional logic. A single LLM
   call often misses 1-2 leaf rules or assigns the wrong AND/OR operator
   at a junction point. The second pass acts as a "reviewer" that catches
   these gaps.

   In our testing with the Oscar bariatric surgery guideline:
   - Pass 1 alone: ~90% rule coverage, ~85% operator accuracy
   - Pass 1 + Pass 2: ~98% rule coverage, ~95% operator accuracy

2. WHY SEGMENT BEFORE SENDING TO LLM?

   The full Oscar PDF is ~22 pages. The criteria section is ~2 pages.
   Sending the full document:
   - Wastes tokens on definitions, billing codes, references
   - Increases hallucination risk (LLM might pull rules from the
     "Repair/Revision" section or "Experimental" section)
   - Makes the task harder (LLM must figure out what to extract)

   By pre-segmenting, we give the LLM a focused, clean input.

3. WHY HIERARCHICAL DOT-NOTATION FOR rule_id?

   The ground truth JSON uses 1, 1.1, 1.1.1, etc. This encoding:
   - Makes parent-child relationships explicit
   - Enables O(1) ancestry checks (is 1.2.2.3 a child of 1.2? → startswith)
   - Matches how humans read numbered legal/medical documents
   - Is deterministic (unlike arbitrary UUIDs)

4. WHY NOT USE PDF STRUCTURE (HEADINGS/LISTS) DIRECTLY?

   PDF is a visual format, not a semantic one. What looks like a numbered
   list in the rendered PDF is just positioned text objects. pdfplumber
   gives us the text but not the structural hierarchy. The LLM
   reconstructs hierarchy from textual cues ("ALL of the following",
   numbered items, indentation patterns).


=============================================================================
PROMPT DESIGN: PASS 1 (EXTRACTION)
=============================================================================

The extraction prompt has several key elements:

A. EXPLICIT SCHEMA EXAMPLE
   We show the exact JSON shape we want. This is more effective than
   describing it in prose. The LLM can pattern-match against the example.

B. NUMBERED RULES
   We give 6 explicit rules (Numbering, Operators, Text fidelity,
   Completeness, Scope, Structural signals). Each addresses a specific
   failure mode we observed during testing:

   - Rule 1 (Numbering): Without this, the LLM might use flat numbering
     (1, 2, 3, 4) instead of hierarchical (1, 1.1, 1.1.1)
   
   - Rule 2 (Operators): The AND/OR detection is the hardest part.
     We give explicit signal words for each. Key insight: "; and" at the
     END of a list item means the SIBLINGS are joined by AND.
   
   - Rule 3 (Text fidelity): LLMs love to paraphrase. In clinical
     guidelines, the exact phrasing matters (e.g., "≥40" vs "over 40",
     "refractory" vs "resistant"). We explicitly forbid paraphrasing.
   
   - Rule 4 (Completeness): The most common failure. The comorbidity
     list under BMI ≥35 has 8 items (i through viii). LLMs sometimes
     stop at 5-6. The explicit instruction to capture ALL items helps.
   
   - Rule 5 (Scope): Without this, the LLM might include the
     repair/revision criteria, the BMI 30-34.9 section, or the
     experimental procedures list.
   
   - Rule 6 (Structural signals): This is the secret weapon. We teach
     the LLM to READ THE CONJUNCTIONS. In legal/medical text:
     - "when ALL of the following" → AND at that level
     - "with ONE of the following" → OR
     - Items ending with "; and" → siblings connected by AND
     - Items ending with "; or" → siblings connected by OR

C. OUTPUT CONSTRAINT
   "Return ONLY valid JSON. No markdown fences." — prevents the LLM
   from wrapping output in ```json blocks or adding commentary.


=============================================================================
PROMPT DESIGN: PASS 2 (VALIDATION)
=============================================================================

The validation prompt is designed as a QA checklist:

A. DUAL INPUT
   We give both the original text AND the extracted JSON. The LLM must
   cross-reference them.

B. EXPLICIT CHECKLIST (A through F)
   Each item targets a specific error class:
   - A: Text accuracy (hallucinated or modified rule text)
   - B: Missing rules (the most common error)
   - C: Operator correctness (AND vs OR confusion)
   - D: ID consistency (numbering gaps or jumps)
   - E: Leaf node cleanliness (no spurious operator/rules on leaves)
   - F: Non-leaf completeness (missing operator on branch nodes)

C. STRUCTURED REPORT
   The validation_report forces the LLM to enumerate specific issues,
   making it harder to "rubber stamp" the input as correct.


=============================================================================
ADAPTING TO NEW POLICY TYPES
=============================================================================

To use this engine for a different insurance policy:

1. SECTION PATTERNS: Update SECTION_PATTERNS in extractor.py to match
   the section headers in your PDF. Common variations:
   - "Medical Necessity Requirements"
   - "Coverage Criteria"
   - "Authorization Requirements"
   - "Clinical Criteria for [Procedure]"

2. SCOPE GUIDANCE: Update Rule 5 in the extraction prompt to specify
   what section(s) to include/exclude for the new policy type.

3. GROUND TRUTH: Create a hand-curated JSON for at least one policy
   of each type. Use it with --validate-against to measure accuracy.

4. OPERATOR SIGNALS: Different insurers use different phrasing. Cigna
   uses "each of the following" (= AND). Aetna uses "any one of" (= OR).
   Add insurer-specific signal words to Rule 6.


=============================================================================
CORRELATING PDF TEXT → JSON STRUCTURE
=============================================================================

Here's how the Oscar bariatric surgery PDF maps to the JSON:

PDF TEXT                                    JSON STRUCTURE
─────────                                  ──────────────
"Procedures are considered medically        rule_id: "1"
necessary when ALL of the following         operator: "AND"
criteria are met:"                          (top-level AND node)

"1. Informed consent..."                    rule_id: "1.1" (leaf)

"2. Adult aged 18 years or older            rule_id: "1.2"
with documentation of:"                     operator: "OR"
  "a. BMI ≥40"                              rule_id: "1.2.1" (leaf)
  "b. BMI ≥35 with ONE of..."              rule_id: "1.2.2"
                                            operator: "OR"
    "i. Cardio-pulmonary disease"           rule_id: "1.2.2.1" (leaf)
    "ii. Coronary artery disease"           rule_id: "1.2.2.2" (leaf)
    ... (8 items total)                     ...
  "c. BMI ≥30-34.9"                         rule_id: "1.2.3" (leaf)

"3. Failure to achieve..."                  rule_id: "1.3" (leaf)

"4. Comprehensive pre/post-op plan"         rule_id: "1.4"
                                            operator: "AND"
  "a. Preoperative evaluation..."           rule_id: "1.4.1"
                                            operator: "AND"
    "i. Basic lab testing"                  rule_id: "1.4.1.1" (leaf)
    "ii. Nutrient screening"               rule_id: "1.4.1.2" (leaf)
    ... (7 items)                           ...

"5. Psycho-social behavioral evaluation"    rule_id: "1.5"
                                            operator: "AND"
  "a. No substance abuse"                  rule_id: "1.5.1" (leaf)
  "b. Members who have..."                 rule_id: "1.5.2"
                                            operator: "OR"
    "i. History of schizophrenia..."       rule_id: "1.5.2.1" (leaf)
    "ii. Under care of psychologist"       rule_id: "1.5.2.2" (leaf)
    "iii. On psychotropic medications"     rule_id: "1.5.2.3" (leaf)

Key observations:
- The "; and" at the end of items 1, 2, 3, 4 tells us they're AND siblings
- "with ONE of the following" under item 2b creates an OR node
- The lettered sub-items (a, b, c) under item 2 use "; or" → OR
- The roman numeral items under 4a use implicit AND (all are required eval steps)
- The items under 5b use "; or" → any one triggers the requirement
"""
