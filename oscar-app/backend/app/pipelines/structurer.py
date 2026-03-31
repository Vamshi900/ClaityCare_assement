"""
Structurer pipeline: extracts text from PDFs and uses LLM to create structured rule trees.

Imports segmentation, prompts, and validation from the shared extraction/ module.
"""

import json
import sys
import os
import logging
from datetime import datetime, timezone

from sqlalchemy import text as sql_text

# ---------------------------------------------------------------------------
# Add extraction module to path so we can import from it
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from extraction.segmenter import segment_criteria_section, extract_text_from_pdf
from extraction.prompts import (
    EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT, EXAMPLE_JSON,
    VALIDATION_SYSTEM_PROMPT, VALIDATION_USER_PROMPT,
)
from extraction.validator import validate_schema, validate_rule_tree_integrity

from app.db import async_session
from app.storage import upload_bytes, download_bytes, get_file_path
from app.llm.client import call_llm_with_json_retry, get_llm_metadata, parse_json_response

log = logging.getLogger(__name__)


async def _structure_single_policy(
    policy_id: str,
    title: str,
    guideline_code: str,
    stored_location: str,
) -> dict:
    """
    Run the full extraction pipeline for a single policy.
    Returns {"status": "validated"|"extracted"|"extraction_failed", "error": ...}.
    """
    # Step 1: Get PDF from storage and extract text
    pdf_path = get_file_path(stored_location)
    pages = extract_text_from_pdf(pdf_path)
    log.info(f"Extracted {len(pages)} pages from {guideline_code}")

    # Store extracted text
    full_text = "\n\n".join(p["text"] for p in pages)
    text_object = f"text/{guideline_code}.txt"
    upload_bytes(text_object, full_text.encode("utf-8"))

    # Step 2: Segment initial criteria section
    criteria_text, initial_only_method = segment_criteria_section(pages)

    # Step 3: LLM Pass 1 - Extract rule tree
    extraction_system = EXTRACTION_SYSTEM_PROMPT.format(insurance_name="Oscar Health")
    extraction_user = EXTRACTION_USER_PROMPT.format(
        criteria_text=criteria_text,
        example_json=EXAMPLE_JSON,
    )

    extracted = await call_llm_with_json_retry(extraction_system, extraction_user)
    log.info(f"Pass 1 complete for {guideline_code}")

    # Step 4: LLM Pass 2 - Validate and fix
    validation_user = VALIDATION_USER_PROMPT.format(
        criteria_text=criteria_text,
        extracted_json=json.dumps(extracted, indent=2),
    )

    try:
        validation_result = await call_llm_with_json_retry(VALIDATION_SYSTEM_PROMPT, validation_user)
    except json.JSONDecodeError:
        log.warning(f"Validation pass JSON failed for {guideline_code}, using Pass 1 output")
        validation_result = {
            "corrected_rules": extracted,
            "validation_report": {
                "is_valid": False,
                "issues_found": ["Validation pass returned invalid JSON"],
            },
        }

    corrected = validation_result.get("corrected_rules", extracted)
    validation_report = validation_result.get("validation_report", {})
    log.info(f"Pass 2 complete for {guideline_code}. Issues: {len(validation_report.get('issues_found', []))}")

    # Step 5: Schema validation
    schema_errors = validate_schema(corrected)
    integrity_errors = validate_rule_tree_integrity(corrected.get("rules", corrected))
    all_errors = schema_errors + integrity_errors

    validation_error = None
    if all_errors:
        validation_error = json.dumps(all_errors)
        log.warning(f"Validation errors for {guideline_code}: {all_errors}")
    else:
        log.info(f"All validation passed for {guideline_code}")

    # Step 6: Store result — mark old versions as not current, compute next version
    llm_metadata = get_llm_metadata()
    llm_metadata["validation_report"] = validation_report
    llm_metadata["schema_errors"] = schema_errors
    llm_metadata["integrity_errors"] = integrity_errors

    async with async_session() as session:
        # Mark old versions as not current
        await session.execute(
            sql_text("UPDATE structured_policies SET is_current = false WHERE policy_id = :pid"),
            {"pid": str(policy_id)},
        )

        # Insert with next version number
        await session.execute(
            sql_text("""
                INSERT INTO structured_policies
                    (policy_id, extracted_text_ref, structured_json, structured_at,
                     llm_metadata, validation_error, initial_only_method,
                     version, is_current)
                VALUES
                    (:policy_id, :extracted_text_ref, :structured_json, :structured_at,
                     :llm_metadata, :validation_error, :initial_only_method,
                     (SELECT COALESCE(MAX(version), 0) + 1 FROM structured_policies WHERE policy_id = :pid2),
                     true)
            """),
            {
                "policy_id": str(policy_id),
                "pid2": str(policy_id),
                "extracted_text_ref": text_object,
                "structured_json": json.dumps(corrected),
                "structured_at": datetime.now(timezone.utc),
                "llm_metadata": json.dumps(llm_metadata),
                "validation_error": validation_error,
                "initial_only_method": initial_only_method,
            },
        )

        # Update policy status
        new_status = "validated" if not validation_error else "extracted"
        await session.execute(
            sql_text("UPDATE policies SET status = :status WHERE id = :pid"),
            {"status": new_status, "pid": str(policy_id)},
        )
        await session.commit()

    return {"status": new_status, "error": validation_error}


async def run_structure(limit: int = 10) -> dict:
    """
    Structure unprocessed policies using the 2-pass LLM pipeline.
    Returns {total, success, failed}.
    """
    log.info(f"Starting structuring pipeline (limit={limit})")

    # Find policies with successful downloads but no structured output
    async with async_session() as session:
        result = await session.execute(
            sql_text("""
                SELECT p.id, p.title, p.guideline_code, d.stored_location
                FROM policies p
                JOIN downloads d ON d.policy_id = p.id
                WHERE d.http_status = 200
                AND d.error IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM structured_policies sp
                    WHERE sp.policy_id = p.id
                )
                ORDER BY p.discovered_at
                LIMIT :limit
            """),
            {"limit": limit},
        )
        pending = result.fetchall()

    total = len(pending)
    success = 0
    failed = 0

    log.info(f"Found {total} policies to structure")

    for row in pending:
        policy_id = row[0]
        title = row[1]
        guideline_code = row[2] or "unknown"
        stored_location = row[3]

        log.info(f"Processing: {guideline_code} - {title}")

        try:
            # Update status to extracting
            async with async_session() as session:
                await session.execute(
                    sql_text("UPDATE policies SET status = 'extracting' WHERE id = :pid"),
                    {"pid": str(policy_id)},
                )
                await session.commit()

            result_info = await _structure_single_policy(
                policy_id, title, guideline_code, stored_location
            )
            success += 1
            log.info(f"Structured {guideline_code} successfully (status={result_info['status']})")

        except Exception as e:
            failed += 1
            log.error(f"Failed to structure {guideline_code}: {e}", exc_info=True)

            # Record the failure
            try:
                async with async_session() as session:
                    # Mark old versions as not current
                    await session.execute(
                        sql_text("UPDATE structured_policies SET is_current = false WHERE policy_id = :pid"),
                        {"pid": str(policy_id)},
                    )

                    await session.execute(
                        sql_text("""
                            INSERT INTO structured_policies
                                (policy_id, structured_json, structured_at,
                                 llm_metadata, validation_error, initial_only_method,
                                 version, is_current)
                            VALUES
                                (:policy_id, :structured_json, :structured_at,
                                 :llm_metadata, :validation_error, :initial_only_method,
                                 (SELECT COALESCE(MAX(version), 0) + 1 FROM structured_policies WHERE policy_id = :pid2),
                                 true)
                        """),
                        {
                            "policy_id": str(policy_id),
                            "pid2": str(policy_id),
                            "structured_json": json.dumps({"error": str(e)}),
                            "structured_at": datetime.now(timezone.utc),
                            "llm_metadata": json.dumps(get_llm_metadata()),
                            "validation_error": str(e),
                            "initial_only_method": "failed",
                        },
                    )

                    # Update policy status to extraction_failed
                    await session.execute(
                        sql_text("UPDATE policies SET status = 'extraction_failed' WHERE id = :pid"),
                        {"pid": str(policy_id)},
                    )
                    await session.commit()
            except Exception as inner_e:
                log.error(f"Failed to record error for {guideline_code}: {inner_e}")

    result = {"total": total, "success": success, "failed": failed}
    log.info(f"Structuring complete: {result}")
    return result


async def run_structure_one(policy_id: str) -> dict:
    """
    Run the structuring pipeline for a single policy by ID.
    Returns {status, error}.
    """
    log.info(f"Starting single-policy extraction for policy_id={policy_id}")

    # Get policy info with download location
    async with async_session() as session:
        result = await session.execute(
            sql_text("""
                SELECT p.id, p.title, p.guideline_code, d.stored_location
                FROM policies p
                JOIN downloads d ON d.policy_id = p.id
                WHERE p.id = :pid
                AND d.http_status = 200
                AND d.error IS NULL
                ORDER BY d.downloaded_at DESC
                LIMIT 1
            """),
            {"pid": policy_id},
        )
        row = result.fetchone()

    if not row:
        raise ValueError(f"Policy {policy_id} not found or has no successful download")

    pid = row[0]
    title = row[1]
    guideline_code = row[2] or "unknown"
    stored_location = row[3]

    # Update status to extracting
    async with async_session() as session:
        await session.execute(
            sql_text("UPDATE policies SET status = 'extracting' WHERE id = :pid"),
            {"pid": str(pid)},
        )
        await session.commit()

    try:
        result_info = await _structure_single_policy(
            pid, title, guideline_code, stored_location
        )
        log.info(f"Single-policy extraction complete for {guideline_code}: {result_info}")
        return result_info
    except Exception as e:
        log.error(f"Single-policy extraction failed for {guideline_code}: {e}", exc_info=True)

        # Update status to extraction_failed
        async with async_session() as session:
            await session.execute(
                sql_text("UPDATE policies SET status = 'extraction_failed' WHERE id = :pid"),
                {"pid": str(pid)},
            )
            await session.commit()

        return {"status": "extraction_failed", "error": str(e)}
