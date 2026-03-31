"""
Discoverer pipeline: scrapes Oscar clinical guidelines page to find PDF links.

Strategy:
  1. Fetch the source page HTML
  2. Try to extract structured data from __NEXT_DATA__ JSON (Next.js)
  3. Fallback: parse <a> tags for guideline hrefs
  4. Each href is a guideline page (e.g. /medical/cg008v11) — visit it
     to resolve the actual PDF URL hosted on Contentful CDN
  5. Insert into DB with ON CONFLICT DO NOTHING for idempotency
"""

import asyncio
import json
import re
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import async_session

log = logging.getLogger(__name__)

OSCAR_BASE = "https://www.hioscar.com"
SOURCE_URL = settings.oscar_source_url
RATE_LIMIT_SECONDS = 0.5

# Regex matching guideline codes: CG013, PG008, MG001, SOC4, etc.
CODE_RE = re.compile(r"((?:cg|pg|mg|soc)\d{1,4})", re.IGNORECASE)
CODE_VERSION_RE = re.compile(
    r"((?:cg|pg|mg|soc)\d{1,4})[\s_]*v?(\d+)", re.IGNORECASE
)


def _extract_code_version(url: str, title: str = "") -> tuple[str | None, str | None]:
    """Extract guideline_code (e.g. CG013) and version (e.g. v11) from URL or title."""
    for source in (url, title):
        m = CODE_VERSION_RE.search(source)
        if m:
            return m.group(1).upper(), f"v{m.group(2)}"
    # Code only (no version)
    for source in (url, title):
        m = CODE_RE.search(source)
        if m:
            return m.group(1).upper(), None
    return None, None


def _is_guideline_href(href: str) -> bool:
    """Check if an href looks like a guideline link."""
    if not href or href.startswith(("http://", "https://", "mailto:", "tel:")):
        # External links — only keep if they're on hioscar.com
        if href.startswith("https://www.hioscar.com/") or href.startswith("http://www.hioscar.com/"):
            return bool(CODE_RE.search(href))
        return False
    # Relative paths: match anything with a guideline code
    return bool(CODE_RE.search(href))


def _extract_title_from_item(item_text: str) -> str:
    """Extract a clean title from an expandable list item or link text."""
    # Strip guideline code/version suffix like "(CG008, Ver. 11)"
    title = re.sub(r"\s*\((?:CG|PG|MG|SOC)\d+.*?\)\s*$", "", item_text, flags=re.IGNORECASE)
    title = title.strip(" –—-,")
    return title or item_text


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a page with retries."""
    for attempt in range(3):
        try:
            resp = await client.get(url, follow_redirects=True, timeout=30.0)
            resp.raise_for_status()
            return resp.text
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            log.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt < 2:
                await asyncio.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after 3 attempts")


def _parse_next_data(html: str) -> list[dict] | None:
    """
    Extract guideline links from __NEXT_DATA__ JSON.

    Oscar uses Next.js with Contentful. The data structure contains
    expandable list modules with items like:
      { "item": "Guideline Title (CG013, Ver. 11)",
        "link": { "text": "PDF", "href": "/medical/cg013v11" } }

    We also walk the full JSON to catch any href matching guideline codes.
    """
    m = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    results = []
    seen_hrefs = set()

    def _walk(obj, context_title="", depth=0):
        if depth > 15:
            return
        if isinstance(obj, dict):
            # Expandable list item: {"item": "...", "link": {"href": "..."}}
            item_title = obj.get("item") or obj.get("title") or obj.get("name") or ""
            link = obj.get("link")
            if isinstance(link, dict):
                href = link.get("href", "")
                if isinstance(href, str) and _is_guideline_href(href):
                    title = _extract_title_from_item(str(item_title)) or link.get("text", "")
                    if href not in seen_hrefs:
                        seen_hrefs.add(href)
                        results.append({"href": href, "title": title})

            # Also check direct href fields
            href = obj.get("href") or obj.get("url") or ""
            if isinstance(href, str) and _is_guideline_href(href) and href not in seen_hrefs:
                title = str(item_title or context_title)
                seen_hrefs.add(href)
                results.append({"href": href, "title": title})

            for k, v in obj.items():
                ctx = str(item_title) if item_title else context_title
                _walk(v, ctx, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, context_title, depth + 1)

    _walk(data)
    return results if results else None


def _parse_html_links(html: str) -> list[dict]:
    """Fallback: parse <a> tags for guideline links."""
    results = []
    seen_hrefs = set()

    for m in re.finditer(
        r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        href = m.group(1)
        link_text = re.sub(r"<[^>]+>", "", m.group(2)).strip()

        if _is_guideline_href(href) and href not in seen_hrefs:
            seen_hrefs.add(href)
            results.append({
                "href": href,
                "title": _extract_title_from_item(link_text),
            })
    return results


async def _find_pdf_on_page(client: httpx.AsyncClient, page_url: str) -> str | None:
    """
    Visit a guideline page to find the Contentful CDN PDF URL.

    Oscar guideline pages embed PDF assets with URLs like:
      //assets.ctfassets.net/plyq12u1bv8a/.../filename.pdf
    """
    try:
        html = await _fetch_page(client, page_url)
    except RuntimeError:
        log.error(f"Could not fetch guideline page: {page_url}")
        return None

    # Look for PDF URLs in href, src, data, or content attributes
    # Contentful CDN pattern: //assets.ctfassets.net/.../*.pdf
    for pattern in [
        r'(?:href|src|data|content)=["\']([^"\']*\.pdf[^"\']*)["\']',
        r'["\']([^"\']*ctfassets\.net[^"\']*\.pdf[^"\']*)["\']',
        r'["\']([^"\']*\.pdf(?:\?[^"\']*)?)["\']',
    ]:
        for m in re.finditer(pattern, html, re.IGNORECASE):
            pdf_url = m.group(1)
            # Normalize protocol-relative URLs
            if pdf_url.startswith("//"):
                pdf_url = "https:" + pdf_url
            elif not pdf_url.startswith("http"):
                pdf_url = OSCAR_BASE + (pdf_url if pdf_url.startswith("/") else f"/{pdf_url}")
            return pdf_url

    return None


async def run_discovery(source_url: str | None = None) -> dict:
    """
    Main discovery pipeline.

    1. Fetch the Oscar clinical guidelines page
    2. Parse guideline entries from __NEXT_DATA__ or HTML links
    3. Visit each guideline page to resolve the PDF URL
    4. Insert into DB (idempotent via ON CONFLICT DO NOTHING)

    Returns {total_found, new_inserted, failed_resolution, strategy}.
    """
    url = source_url or SOURCE_URL
    log.info(f"Starting discovery from: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; OscarGuidelinesBot/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async with httpx.AsyncClient(headers=headers) as client:
        html = await _fetch_page(client, url)

        # Strategy 1: __NEXT_DATA__
        next_data_entries = _parse_next_data(html)
        html_entries = _parse_html_links(html)

        if next_data_entries:
            entries = next_data_entries
            strategy = "__NEXT_DATA__"
        else:
            entries = html_entries
            strategy = "html_links"

        # Coverage report — log both strategies for transparency
        log.info(
            f"Discovery coverage: __NEXT_DATA__={len(next_data_entries or [])} entries, "
            f"html_links={len(html_entries)} entries. Using: {strategy}"
        )
        log.info(f"Selected {len(entries)} guideline entries via {strategy}")

        # Resolve each entry to a PDF URL
        policies = []
        failed_resolution = 0
        for i, entry in enumerate(entries):
            href = entry["href"]
            title = entry.get("title", "")

            # Normalize URL
            if not href.startswith("http"):
                full_url = OSCAR_BASE + (href if href.startswith("/") else f"/{href}")
            else:
                full_url = href

            # Visit guideline page to resolve actual PDF URL
            await asyncio.sleep(RATE_LIMIT_SECONDS)
            pdf_url = await _find_pdf_on_page(client, full_url)
            if not pdf_url:
                log.warning(f"No PDF found on page: {full_url}")
                failed_resolution += 1
                # Store with the page URL as pdf_url so we still track it
                pdf_url = full_url

            code, version = _extract_code_version(href, title)
            if not title:
                title = code or "Unknown Guideline"

            policies.append({
                "title": title,
                "guideline_code": code,
                "version": version,
                "pdf_url": pdf_url,
                "source_page_url": url,
            })

            if (i + 1) % 25 == 0:
                log.info(f"Progress: {i + 1}/{len(entries)} entries resolved")

        log.info(f"Resolved {len(policies)} policies ({failed_resolution} without direct PDF URLs)")

    # Insert into database with ON CONFLICT DO NOTHING
    new_inserted = 0
    async with async_session() as session:
        for p in policies:
            result = await session.execute(
                text("""
                    INSERT INTO policies (title, guideline_code, version, pdf_url, source_page_url, discovered_at)
                    VALUES (:title, :guideline_code, :version, :pdf_url, :source_page_url, :discovered_at)
                    ON CONFLICT (pdf_url) DO NOTHING
                    RETURNING id
                """),
                {
                    "title": p["title"],
                    "guideline_code": p["guideline_code"],
                    "version": p["version"],
                    "pdf_url": p["pdf_url"],
                    "source_page_url": p["source_page_url"],
                    "discovered_at": datetime.now(timezone.utc),
                },
            )
            row = result.fetchone()
            if row:
                new_inserted += 1
        await session.commit()

    result = {
        "total_found": len(policies),
        "new_inserted": new_inserted,
        "failed_resolution": failed_resolution,
        "strategy": strategy,
    }
    log.info(f"Discovery complete: {result}")
    return result
