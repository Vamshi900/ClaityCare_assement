"""
Segmenter — PDF text extraction and criteria section segmentation.

Extracts text from PDF files and identifies the INITIAL medical necessity
criteria section using a 3-tier waterfall strategy.
"""

import re
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section detection patterns
# ---------------------------------------------------------------------------
SECTION_PATTERNS = {
    # Patterns that signal the START of initial criteria
    "initial_start": [
        r"Initial\s+(?:Authorization\s+)?Criteria",
        r"Initial\s+(?:Medical\s+)?Necessity\s+Criteria",
        r"Initial\s+Treatment\s+Criteria",
        r"Initial\s+Approval\s+Criteria",
        r"Criteria\s+for\s+Initial\s+(?:Authorization|Approval|Treatment)",
    ],
    # Generic criteria start (used when no explicit "initial" section found)
    "criteria_start": [
        r"Criteria\s+for\s+Medically\s+Necessary",
        r"Medical\s+Necessity\s+Criteria",
        r"Clinical\s+Indications",
        r"Procedures?\s+(?:are|is)\s+considered\s+medically\s+necessary\s+when",
    ],
    # Patterns that signal the END of the initial section (continuation starts)
    "continuation_markers": [
        r"Continuation\s+(?:of\s+)?(?:Therapy\s+)?Criteria",
        r"Cont(?:inuation|inued)\s+(?:Authorization|Approval|Treatment)",
        r"Re-?[Aa]uthorization\s+Criteria",
        r"Renewal\s+Criteria",
        r"Maintenance\s+(?:Therapy\s+)?Criteria",
        r"Criteria\s+for\s+Continuation",
        r"Criteria\s+for\s+Re-?[Aa]uthorization",
        r"Follow[\s-]?[Uu]p\s+(?:Therapy\s+)?Criteria",
        r"Ongoing\s+(?:Therapy\s+)?Criteria",
        r"Reassessment\s+Criteria",
        r"Subsequent\s+(?:Authorization\s+)?Criteria",
    ],
    # General end markers (document sections after all criteria)
    "end_markers": [
        r"Experimental\s+or\s+Investigational",
        r"Not\s+Medically\s+Necessary",
        r"Applicable\s+Billing\s+Codes",
        r"Repair,\s+Replacement",
        r"Relative\s+Contraindications",
        r"Coding\s+Information",
        r"References",
    ],
}


# ===========================================================================
# PDF Text Extraction
# ===========================================================================
def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """
    Extract text page-by-page using multiple strategies.
    Strategy 1: pdftotext (poppler) — best for preserving word spacing.
    Strategy 2: pdfplumber — fallback if pdftotext unavailable.
    Returns list of {"page": int, "text": str}.
    """
    import subprocess
    import pdfplumber

    pages = []

    # Try pdftotext first (better word spacing)
    try:
        # Get page count
        info = subprocess.run(
            ["pdfinfo", pdf_path], capture_output=True, text=True, check=True
        )
        page_count = 0
        for line in info.stdout.split("\n"):
            if line.startswith("Pages:"):
                page_count = int(line.split(":")[1].strip())
                break

        for i in range(1, page_count + 1):
            result = subprocess.run(
                ["pdftotext", "-f", str(i), "-l", str(i), "-layout", pdf_path, "-"],
                capture_output=True, text=True, check=True,
            )
            text = result.stdout
            pages.append({"page": i, "text": text})
            log.info(f"Extracted page {i} (pdftotext): {len(text)} chars")

        if pages:
            return pages
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        log.warning(f"pdftotext failed, falling back to pdfplumber: {e}")

    # Fallback: pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page": i, "text": text})
            log.info(f"Extracted page {i} (pdfplumber): {len(text)} chars")
    return pages


# ===========================================================================
# Section Segmentation
# ===========================================================================
MIN_SECTION_LENGTH = 500  # Sections shorter than this are likely TOC entries, skip them


def _find_end_boundary(full_text: str, start_idx: int) -> tuple[int, bool]:
    """Find the nearest end boundary (continuation or general end marker).
    Returns (end_idx, found_continuation)."""
    end_idx = len(full_text)
    found_continuation = False
    for pattern in SECTION_PATTERNS["continuation_markers"]:
        match = re.search(pattern, full_text[start_idx + 50:], re.IGNORECASE)
        if match:
            candidate = start_idx + 50 + match.start()
            if candidate < end_idx:
                end_idx = candidate
                found_continuation = True
                log.info(f"Found continuation marker at char {end_idx} via: {pattern}")
    for pattern in SECTION_PATTERNS["end_markers"]:
        match = re.search(pattern, full_text[start_idx + 50:], re.IGNORECASE)
        if match:
            candidate = start_idx + 50 + match.start()
            if candidate < end_idx:
                end_idx = candidate
                log.info(f"Found end marker at char {end_idx} via: {pattern}")
    return end_idx, found_continuation


def segment_criteria_section(pages: list[dict]) -> tuple[str, str]:
    """
    Extract the INITIAL medical necessity criteria section from the PDF text.

    Selection logic (in priority order):
      1. If an explicit "Initial Criteria" section heading exists, extract
         from there to the next continuation/end marker.
      2. If no explicit "Initial" heading, find the first generic criteria
         section and extract up to any continuation marker or end marker.
      3. If no markers found at all, return the full text.

    If a match produces a section shorter than MIN_SECTION_LENGTH (likely a
    table-of-contents entry), it is skipped and the next match is tried.

    Returns (section_text, selection_method) where selection_method is one of:
      - "explicit_initial" — found an "Initial Criteria" heading
      - "first_criteria_before_continuation" — first criteria section, stopped at continuation
      - "first_criteria_section" — first criteria section, no continuation found
      - "full_document" — no section markers found, using full text
    """
    full_text = "\n\n".join(
        f"--- PAGE {p['page']} ---\n{p['text']}" for p in pages
    )

    # --- Strategy 1: Look for explicit "Initial Criteria" heading ---
    for pattern in SECTION_PATTERNS["initial_start"]:
        for match in re.finditer(pattern, full_text, re.IGNORECASE):
            start_idx = full_text.rfind("\n", 0, match.start()) + 1
            end_idx, _ = _find_end_boundary(full_text, start_idx)
            section = full_text[start_idx:end_idx].strip()
            if len(section) >= MIN_SECTION_LENGTH:
                log.info(f"Found explicit INITIAL section at char {start_idx}: {len(section)} chars")
                return section, "explicit_initial"
            else:
                log.info(f"Skipping short INITIAL match at char {start_idx}: {len(section)} chars (likely TOC)")

    # --- Strategy 2: Generic criteria section, bounded by continuation ---
    for pattern in SECTION_PATTERNS["criteria_start"]:
        for match in re.finditer(pattern, full_text, re.IGNORECASE):
            start_idx = full_text.rfind("\n", 0, match.start()) + 1
            end_idx, found_continuation = _find_end_boundary(full_text, start_idx)
            section = full_text[start_idx:end_idx].strip()
            if len(section) >= MIN_SECTION_LENGTH:
                method = "first_criteria_before_continuation" if found_continuation else "first_criteria_section"
                log.info(f"Found criteria section at char {start_idx}: {len(section)} chars ({method})")
                return section, method
            else:
                log.info(f"Skipping short criteria match at char {start_idx}: {len(section)} chars (likely TOC)")

    # --- Strategy 3: Full document fallback ---
    log.warning("No criteria section markers found — using full document")
    return full_text.strip(), "full_document"
