"""
FastAPI application with all routes for Oscar Guidelines API.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.config import settings
from app.db import async_session
from app.schemas import JobCreate
from app.storage import get_file_path, file_exists, download_bytes, setup_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="Oscar Guidelines API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    setup_storage()
    log.info("Oscar Guidelines API started")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Background job runners
# ---------------------------------------------------------------------------
async def _run_discovery(job_id: str, source_url: str | None):
    """Background task for discovery pipeline."""
    async with async_session() as session:
        await session.execute(
            text("UPDATE jobs SET status = 'running', started_at = :now WHERE id = :id"),
            {"id": job_id, "now": datetime.now(timezone.utc)},
        )
        await session.commit()

    try:
        from app.pipelines.discoverer import run_discovery
        result = await run_discovery(source_url)

        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'completed', finished_at = :now, metadata = :meta
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "meta": json.dumps(result),
                },
            )
            await session.commit()
    except Exception as e:
        log.error(f"Discovery job {job_id} failed: {e}", exc_info=True)
        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'failed', finished_at = :now, error = :error
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "error": str(e),
                },
            )
            await session.commit()


async def _run_download(job_id: str):
    """Background task for download pipeline with status tracking."""
    async with async_session() as session:
        await session.execute(
            text("UPDATE jobs SET status = 'running', started_at = :now WHERE id = :id"),
            {"id": job_id, "now": datetime.now(timezone.utc)},
        )
        await session.commit()

    try:
        from app.pipelines.downloader import run_download
        result = await run_download()

        # After download completes, update policy statuses
        async with async_session() as session:
            # Mark successfully downloaded policies
            await session.execute(
                text("""
                    UPDATE policies SET status = 'downloaded'
                    WHERE status = 'discovered'
                    AND EXISTS (
                        SELECT 1 FROM downloads d
                        WHERE d.policy_id = policies.id
                        AND d.http_status = 200 AND d.error IS NULL
                    )
                """)
            )
            # Mark failed downloads
            await session.execute(
                text("""
                    UPDATE policies SET status = 'download_failed'
                    WHERE status = 'discovered'
                    AND EXISTS (
                        SELECT 1 FROM downloads d
                        WHERE d.policy_id = policies.id
                        AND d.error IS NOT NULL
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM downloads d
                        WHERE d.policy_id = policies.id
                        AND d.http_status = 200 AND d.error IS NULL
                    )
                """)
            )
            await session.commit()

        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'completed', finished_at = :now, metadata = :meta
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "meta": json.dumps(result),
                },
            )
            await session.commit()
    except Exception as e:
        log.error(f"Download job {job_id} failed: {e}", exc_info=True)
        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'failed', finished_at = :now, error = :error
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "error": str(e),
                },
            )
            await session.commit()


async def _run_structure(job_id: str):
    """Background task for structuring pipeline."""
    async with async_session() as session:
        await session.execute(
            text("UPDATE jobs SET status = 'running', started_at = :now WHERE id = :id"),
            {"id": job_id, "now": datetime.now(timezone.utc)},
        )
        await session.commit()

    try:
        from app.pipelines.structurer import run_structure
        result = await run_structure()

        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'completed', finished_at = :now, metadata = :meta
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "meta": json.dumps(result),
                },
            )
            await session.commit()
    except Exception as e:
        log.error(f"Structure job {job_id} failed: {e}", exc_info=True)
        async with async_session() as session:
            await session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'failed', finished_at = :now, error = :error
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "now": datetime.now(timezone.utc),
                    "error": str(e),
                },
            )
            await session.commit()


async def _run_structure_one(policy_id: str):
    """Background task for single-policy extraction."""
    try:
        from app.pipelines.structurer import run_structure_one
        result = await run_structure_one(policy_id)
        log.info(f"Single-policy extraction done for {policy_id}: {result}")
    except Exception as e:
        log.error(f"Single-policy extraction failed for {policy_id}: {e}", exc_info=True)


async def _run_retry_download(policy_id: str):
    """Background task to retry a failed download for one policy."""
    try:
        from app.pipelines.downloader import run_download
        # We reuse run_download but it will only pick up policies without
        # successful downloads. We ensure this policy is eligible first.
        async with async_session() as session:
            await session.execute(
                text("UPDATE policies SET status = 'discovered' WHERE id = :pid"),
                {"pid": policy_id},
            )
            # Delete old failed download records so it gets re-attempted
            await session.execute(
                text("DELETE FROM downloads WHERE policy_id = :pid AND error IS NOT NULL"),
                {"pid": policy_id},
            )
            await session.commit()

        result = await run_download()

        # Update status based on result
        async with async_session() as session:
            dl_result = await session.execute(
                text("""
                    SELECT error FROM downloads
                    WHERE policy_id = :pid
                    ORDER BY downloaded_at DESC LIMIT 1
                """),
                {"pid": policy_id},
            )
            dl_row = dl_result.fetchone()
            if dl_row and dl_row[0] is None:
                await session.execute(
                    text("UPDATE policies SET status = 'downloaded' WHERE id = :pid"),
                    {"pid": policy_id},
                )
            else:
                await session.execute(
                    text("UPDATE policies SET status = 'download_failed' WHERE id = :pid"),
                    {"pid": policy_id},
                )
            await session.commit()

    except Exception as e:
        log.error(f"Retry download failed for {policy_id}: {e}", exc_info=True)
        async with async_session() as session:
            await session.execute(
                text("UPDATE policies SET status = 'download_failed' WHERE id = :pid"),
                {"pid": policy_id},
            )
            await session.commit()


# ---------------------------------------------------------------------------
# Jobs API
# ---------------------------------------------------------------------------
@app.post("/api/jobs")
async def create_job(body: JobCreate):
    """Create a new background job (discovery, download, structure)."""
    if body.type not in ("discovery", "download", "structure"):
        raise HTTPException(status_code=400, detail=f"Invalid job type: {body.type}")

    async with async_session() as session:
        result = await session.execute(
            text("""
                INSERT INTO jobs (type, status, source_url, created_at)
                VALUES (:type, 'queued', :source_url, :now)
                RETURNING id, type, status, source_url, started_at, finished_at, metadata, error, created_at
            """),
            {
                "type": body.type,
                "source_url": body.source_url,
                "now": datetime.now(timezone.utc),
            },
        )
        row = result.fetchone()
        await session.commit()

    job_id = str(row[0])

    # Dispatch background task
    if body.type == "discovery":
        asyncio.create_task(_run_discovery(job_id, body.source_url))
    elif body.type == "download":
        asyncio.create_task(_run_download(job_id))
    elif body.type == "structure":
        asyncio.create_task(_run_structure(job_id))

    return {
        "id": row[0],
        "type": row[1],
        "status": row[2],
        "source_url": row[3],
        "started_at": row[4],
        "finished_at": row[5],
        "metadata_": row[6],
        "error": row[7],
        "created_at": row[8],
    }


@app.get("/api/jobs")
async def list_jobs():
    """List all jobs, most recent first."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT id, type, status, source_url, started_at, finished_at, metadata, error, created_at
                FROM jobs
                ORDER BY created_at DESC
            """)
        )
        rows = result.fetchall()

    return [
        {
            "id": row[0],
            "type": row[1],
            "status": row[2],
            "source_url": row[3],
            "started_at": row[4],
            "finished_at": row[5],
            "metadata_": row[6],
            "error": row[7],
            "created_at": row[8],
        }
        for row in rows
    ]


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job detail by ID."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT id, type, status, source_url, started_at, finished_at, metadata, error, created_at
                FROM jobs WHERE id = :id
            """),
            {"id": job_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": row[0],
        "type": row[1],
        "status": row[2],
        "source_url": row[3],
        "started_at": row[4],
        "finished_at": row[5],
        "metadata_": row[6],
        "error": row[7],
        "created_at": row[8],
    }


# ---------------------------------------------------------------------------
# Policies API
# ---------------------------------------------------------------------------
@app.get("/api/policies")
async def list_policies(search: str | None = Query(None)):
    """List all policies with download/structured status."""
    async with async_session() as session:
        if search:
            result = await session.execute(
                text("""
                    SELECT
                        p.id, p.title, p.guideline_code, p.version, p.pdf_url,
                        p.source_page_url, p.discovered_at, p.status,
                        EXISTS(SELECT 1 FROM downloads d WHERE d.policy_id = p.id AND d.http_status = 200 AND d.error IS NULL) as has_download,
                        EXISTS(SELECT 1 FROM structured_policies sp WHERE sp.policy_id = p.id) as has_structured_tree
                    FROM policies p
                    WHERE p.title ILIKE :search
                       OR p.guideline_code ILIKE :search
                    ORDER BY p.discovered_at DESC
                """),
                {"search": f"%{search}%"},
            )
        else:
            result = await session.execute(
                text("""
                    SELECT
                        p.id, p.title, p.guideline_code, p.version, p.pdf_url,
                        p.source_page_url, p.discovered_at, p.status,
                        EXISTS(SELECT 1 FROM downloads d WHERE d.policy_id = p.id AND d.http_status = 200 AND d.error IS NULL) as has_download,
                        EXISTS(SELECT 1 FROM structured_policies sp WHERE sp.policy_id = p.id) as has_structured_tree
                    FROM policies p
                    ORDER BY p.discovered_at DESC
                """)
            )
        rows = result.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "guideline_code": row[2],
            "version": row[3],
            "pdf_url": row[4],
            "source_page_url": row[5],
            "discovered_at": row[6],
            "status": row[7],
            "has_download": row[8],
            "has_structured_tree": row[9],
        }
        for row in rows
    ]


@app.get("/api/policies/{policy_id}")
async def get_policy(policy_id: str):
    """Get policy detail by ID."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT
                    p.id, p.title, p.guideline_code, p.version, p.pdf_url,
                    p.source_page_url, p.discovered_at, p.status,
                    EXISTS(SELECT 1 FROM downloads d WHERE d.policy_id = p.id AND d.http_status = 200 AND d.error IS NULL) as has_download,
                    EXISTS(SELECT 1 FROM structured_policies sp WHERE sp.policy_id = p.id) as has_structured_tree
                FROM policies p
                WHERE p.id = :id
            """),
            {"id": policy_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Policy not found")

    # Get download status
    async with async_session() as session:
        dl_result = await session.execute(
            text("""
                SELECT http_status, error, stored_location
                FROM downloads
                WHERE policy_id = :id
                ORDER BY downloaded_at DESC
                LIMIT 1
            """),
            {"id": policy_id},
        )
        dl_row = dl_result.fetchone()

    download_status = None
    if dl_row:
        if dl_row[1]:
            download_status = f"failed: {dl_row[1]}"
        elif dl_row[0] == 200:
            download_status = "success"
        else:
            download_status = f"http_{dl_row[0]}"

    # Get structured JSON
    async with async_session() as session:
        sp_result = await session.execute(
            text("""
                SELECT structured_json
                FROM structured_policies
                WHERE policy_id = :id AND is_current = true
                ORDER BY structured_at DESC
                LIMIT 1
            """),
            {"id": policy_id},
        )
        sp_row = sp_result.fetchone()

    structured_json = sp_row[0] if sp_row else None

    return {
        "id": row[0],
        "title": row[1],
        "guideline_code": row[2],
        "version": row[3],
        "pdf_url": row[4],
        "source_page_url": row[5],
        "discovered_at": row[6],
        "status": row[7],
        "has_download": row[8],
        "has_structured_tree": row[9],
        "download_status": download_status,
        "structured_json": structured_json,
    }


@app.get("/api/policies/{policy_id}/tree")
async def get_policy_tree(policy_id: str, version: int = None):
    """Get the structured JSON rule tree for a policy."""
    async with async_session() as session:
        if version is not None:
            result = await session.execute(
                text("""
                    SELECT sp.structured_json, sp.llm_metadata, sp.validation_error,
                           sp.initial_only_method, sp.version, sp.is_current
                    FROM structured_policies sp
                    WHERE sp.policy_id = :id AND sp.version = :version
                    LIMIT 1
                """),
                {"id": policy_id, "version": version},
            )
        else:
            result = await session.execute(
                text("""
                    SELECT sp.structured_json, sp.llm_metadata, sp.validation_error,
                           sp.initial_only_method, sp.version, sp.is_current
                    FROM structured_policies sp
                    WHERE sp.policy_id = :id AND sp.is_current = true
                    ORDER BY sp.structured_at DESC
                    LIMIT 1
                """),
                {"id": policy_id},
            )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No structured tree found for this policy")

    return {
        "structured_json": row[0],
        "llm_metadata": row[1],
        "validation_error": row[2],
        "initial_only_method": row[3],
        "version": row[4],
        "is_current": row[5],
    }


@app.get("/api/policies/{policy_id}/pdf-url")
async def get_policy_pdf(policy_id: str):
    """Return the local PDF file or its path."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT stored_location
                FROM downloads
                WHERE policy_id = :id AND http_status = 200 AND error IS NULL
                ORDER BY downloaded_at DESC
                LIMIT 1
            """),
            {"id": policy_id},
        )
        row = result.fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="No downloaded PDF found for this policy")

    stored_location = row[0]
    file_path_str = get_file_path(stored_location)

    if not file_exists(stored_location):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    return FileResponse(
        path=file_path_str,
        media_type="application/pdf",
        filename=stored_location.split("/")[-1],
    )


@app.get("/api/policies/{policy_id}/text")
async def get_policy_text(policy_id: str):
    """Return the extracted text for a policy."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT extracted_text_ref
                FROM structured_policies
                WHERE policy_id = :id AND is_current = true
                ORDER BY structured_at DESC
                LIMIT 1
            """),
            {"id": policy_id},
        )
        row = result.fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="No extracted text found for this policy")

    text_ref = row[0]
    try:
        content = download_bytes(text_ref)
        return {"text": content.decode("utf-8"), "ref": text_ref}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Text file not found on disk")


@app.get("/api/policies/{policy_id}/versions")
async def get_versions(policy_id: str):
    """List all extraction versions for a policy."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT version, is_current, structured_at, llm_metadata, validation_error
                FROM structured_policies
                WHERE policy_id = :pid
                ORDER BY version DESC
            """),
            {"pid": policy_id},
        )
        rows = result.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No versions found for this policy")

    return [
        {
            "version": row[0],
            "is_current": row[1],
            "structured_at": row[2],
            "llm_metadata": row[3],
            "validation_error": row[4],
        }
        for row in rows
    ]


@app.post("/api/policies/{policy_id}/extract")
async def extract_policy(policy_id: str):
    """Trigger extraction for ONE policy."""
    # Verify policy exists and is downloaded
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT p.id, p.status
                FROM policies p
                WHERE p.id = :pid
            """),
            {"pid": policy_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Policy not found")

    # Check that a successful download exists
    async with async_session() as session:
        dl_result = await session.execute(
            text("""
                SELECT id FROM downloads
                WHERE policy_id = :pid AND http_status = 200 AND error IS NULL
                LIMIT 1
            """),
            {"pid": policy_id},
        )
        if not dl_result.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Policy has no successful download. Download it first.",
            )

    # Set status to extracting
    async with async_session() as session:
        await session.execute(
            text("UPDATE policies SET status = 'extracting' WHERE id = :pid"),
            {"pid": policy_id},
        )
        await session.commit()

    # Launch background task
    asyncio.create_task(_run_structure_one(policy_id))

    return {"message": "Extraction started", "policy_id": policy_id}


@app.post("/api/policies/{policy_id}/retry")
async def retry_policy(policy_id: str):
    """Retry a failed download or extraction."""
    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, status FROM policies WHERE id = :pid"),
            {"pid": policy_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Policy not found")

    current_status = row[1]

    if current_status == "download_failed":
        # Retry download
        asyncio.create_task(_run_retry_download(policy_id))
        return {"message": "Download retry started", "policy_id": policy_id}

    elif current_status == "extraction_failed":
        # Retry extraction
        async with async_session() as session:
            await session.execute(
                text("UPDATE policies SET status = 'extracting' WHERE id = :pid"),
                {"pid": policy_id},
            )
            await session.commit()
        asyncio.create_task(_run_structure_one(policy_id))
        return {"message": "Extraction retry started", "policy_id": policy_id}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Policy status is '{current_status}' — retry is only available for 'download_failed' or 'extraction_failed'",
        )


# ---------------------------------------------------------------------------
# Stats API
# ---------------------------------------------------------------------------
@app.get("/api/stats")
async def get_stats():
    """Return aggregate counts."""
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT
                    (SELECT COUNT(*) FROM policies) as total_policies,
                    (SELECT COUNT(*) FROM downloads WHERE http_status = 200 AND error IS NULL) as total_downloaded,
                    (SELECT COUNT(*) FROM structured_policies WHERE validation_error IS NULL AND is_current = true) as total_structured,
                    (SELECT COUNT(*) FROM downloads WHERE error IS NOT NULL) as total_failed_downloads,
                    (SELECT COUNT(*) FROM structured_policies WHERE validation_error IS NOT NULL AND is_current = true) as total_validation_errors
            """)
        )
        row = result.fetchone()

    return {
        "total_policies": row[0],
        "total_downloaded": row[1],
        "total_structured": row[2],
        "total_failed_downloads": row[3],
        "total_validation_errors": row[4],
    }
