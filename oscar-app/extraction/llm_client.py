"""
LLM Client — Anthropic API calls for extraction and validation passes.
"""

import json
import re
import logging

from anthropic import Anthropic

from extraction.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
    EXAMPLE_JSON,
    VALIDATION_SYSTEM_PROMPT,
    VALIDATION_USER_PROMPT,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192
LLM_MAX_RETRIES = 2  # Retry on malformed JSON


def _parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON from LLM output."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def extract_rules_with_llm(
    client: Anthropic,
    criteria_text: str,
    insurance_name: str = "Oscar Health",
) -> dict:
    """
    LLM Pass 1: Extract the rule tree from the criteria section.
    Retries up to LLM_MAX_RETRIES times if the LLM returns malformed JSON.
    """
    log.info("LLM Pass 1: Extracting rule tree...")

    messages = [
        {
            "role": "user",
            "content": EXTRACTION_USER_PROMPT.format(
                criteria_text=criteria_text,
                example_json=EXAMPLE_JSON,
            ),
        }
    ]

    system_prompt = EXTRACTION_SYSTEM_PROMPT.format(insurance_name=insurance_name)

    last_error = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        )

        raw = response.content[0].text.strip()

        try:
            result = _parse_llm_json(raw)
            log.info(f"Pass 1 complete (attempt {attempt}). Top-level keys: {list(result.keys())}")
            # Attach prompts for intermediate logging
            result["_llm_input"] = {"system": system_prompt, "messages": messages}
            result["_llm_raw_output"] = raw
            return result
        except json.JSONDecodeError as e:
            last_error = e
            log.warning(f"Pass 1 attempt {attempt}/{LLM_MAX_RETRIES}: malformed JSON — {e}")
            log.warning(f"Raw output (first 300 chars): {raw[:300]}")

            if attempt < LLM_MAX_RETRIES:
                # Add the failed response and a correction prompt for the retry
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": "Your previous response was not valid JSON. "
                    "Please return ONLY valid JSON with no markdown fences, "
                    "no commentary, and no trailing commas.",
                })

    log.error(f"Pass 1 failed after {LLM_MAX_RETRIES} attempts: {last_error}")
    raise last_error


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

    user_content = VALIDATION_USER_PROMPT.format(
        criteria_text=criteria_text,
        extracted_json=json.dumps(extracted, indent=2),
    )
    messages = [{"role": "user", "content": user_content}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=VALIDATION_SYSTEM_PROMPT,
        messages=messages,
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Attach prompts for intermediate logging
    _llm_io = {
        "system": VALIDATION_SYSTEM_PROMPT,
        "messages": messages,
        "raw_output": raw,
    }

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error(f"Validation pass failed to parse: {e}")
        log.error(f"Raw output (first 500 chars): {raw[:500]}")
        return extracted, {"issues_found": ["Validation pass failed"], "is_valid": False, "_llm_io": _llm_io}

    corrected = result.get("corrected_rules", extracted)
    report = result.get("validation_report", {})
    report["_llm_io"] = _llm_io

    issues = report.get("issues_found", [])
    log.info(f"Pass 2 complete. Issues found: {len(issues)}")
    for issue in issues:
        log.warning(f"  - {issue}")

    return corrected, report
