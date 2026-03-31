"""
Downloader pipeline: downloads PDFs for discovered policies.

Uses exponential backoff with jitter to avoid thundering herd on retries.
"""

import asyncio
import hashlib
import logging
import random
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db import async_session
from app.storage import upload_bytes

log = logging.getLogger(__name__)

RATE_LIMIT_SECONDS = 0.5
MAX_RETRIES = 3


async def run_download() -> dict:
    """
    Download all PDFs that haven't been successfully downloaded yet.
    Returns {total, success, failed}.
    """
    log.info("Starting download pipeline")

    # Find policies without a successful download
    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT p.id, p.pdf_url, p.guideline_code, p.title
                FROM policies p
                WHERE NOT EXISTS (
                    SELECT 1 FROM downloads d
                    WHERE d.policy_id = p.id
                    AND d.http_status = 200
                    AND d.error IS NULL
                )
                ORDER BY p.discovered_at
            """)
        )
        pending = result.fetchall()

    total = len(pending)
    success = 0
    failed = 0

    log.info(f"Found {total} policies needing download")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OscarGuidelinesBot/1.0)",
        "Accept": "application/pdf,*/*",
    }

    async with httpx.AsyncClient(headers=headers, timeout=60.0) as client:
        for row in pending:
            policy_id = row[0]
            pdf_url = row[1]
            guideline_code = row[2] or "unknown"
            title = row[3]

            log.info(f"Downloading: {guideline_code} - {title}")

            last_error = None
            http_status = None
            content = None

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = await client.get(pdf_url, follow_redirects=True)
                    http_status = resp.status_code

                    if resp.status_code == 200:
                        content = resp.content
                        last_error = None
                        break
                    else:
                        last_error = f"HTTP {resp.status_code}"
                        log.warning(f"Attempt {attempt}/{MAX_RETRIES} for {guideline_code}: {last_error}")

                except (httpx.HTTPError, httpx.TimeoutException) as e:
                    last_error = str(e)
                    http_status = None
                    log.warning(f"Attempt {attempt}/{MAX_RETRIES} for {guideline_code}: {last_error}")

                if attempt < MAX_RETRIES:
                    # Exponential backoff with jitter to avoid thundering herd
                    base_backoff = 2 ** (attempt - 1)
                    jitter = random.uniform(0, base_backoff * 0.5)
                    await asyncio.sleep(base_backoff + jitter)

            # Record result
            async with async_session() as session:
                if content and not last_error:
                    # Compute hash for dedup
                    content_hash = hashlib.sha256(content).hexdigest()

                    # Check if we already have this exact file
                    existing = await session.execute(
                        text("SELECT id FROM downloads WHERE content_hash = :hash AND error IS NULL"),
                        {"hash": content_hash},
                    )
                    if existing.fetchone():
                        log.info(f"Skipping duplicate content for {guideline_code} (hash: {content_hash[:12]}...)")

                    # Store file
                    object_name = f"pdfs/{guideline_code}.pdf"
                    upload_bytes(object_name, content)

                    await session.execute(
                        text("""
                            INSERT INTO downloads (policy_id, stored_location, downloaded_at, http_status,
                                                   file_size_bytes, content_hash, attempt_number)
                            VALUES (:policy_id, :stored_location, :downloaded_at, :http_status,
                                    :file_size_bytes, :content_hash, :attempt_number)
                        """),
                        {
                            "policy_id": str(policy_id),
                            "stored_location": object_name,
                            "downloaded_at": datetime.now(timezone.utc),
                            "http_status": 200,
                            "file_size_bytes": len(content),
                            "content_hash": content_hash,
                            "attempt_number": MAX_RETRIES if last_error else 1,
                        },
                    )
                    await session.commit()
                    success += 1
                    log.info(f"Downloaded {guideline_code}: {len(content)} bytes")
                else:
                    await session.execute(
                        text("""
                            INSERT INTO downloads (policy_id, downloaded_at, http_status, error, attempt_number)
                            VALUES (:policy_id, :downloaded_at, :http_status, :error, :attempt_number)
                        """),
                        {
                            "policy_id": str(policy_id),
                            "downloaded_at": datetime.now(timezone.utc),
                            "http_status": http_status,
                            "error": last_error or "Unknown error",
                            "attempt_number": MAX_RETRIES,
                        },
                    )
                    await session.commit()
                    failed += 1
                    log.error(f"Failed to download {guideline_code}: {last_error}")

            await asyncio.sleep(RATE_LIMIT_SECONDS)

    result = {"total": total, "success": success, "failed": failed}
    log.info(f"Download complete: {result}")
    return result
