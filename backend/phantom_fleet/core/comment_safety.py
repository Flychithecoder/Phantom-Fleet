"""Safety filter for AI-generated comment candidates.

Drops any candidate that:
  - contains a URL / link
  - contains an @-mention
  - contains a phone number
  - contains an email address
  - contains a word or phrase from the loaded blocklist file

The blocklist lives at `backend/.data/comment_blocklist.txt`. Lines
starting with `#` are comments; blank lines ignored. Match is
case-insensitive substring; the file is loaded on first use and
cached, with an opt-in refresh via `clear_blocklist_cache()` for tests.

The filter is deliberately conservative — a false positive is cheap
(regenerate), a false negative lets unsafe text into the approval
queue. Approval is still owner-gated downstream, but this filter
keeps the queue readable.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

_REPO = Path(__file__).resolve().parents[3]
_BLOCKLIST_PATH = _REPO / "backend" / ".data" / "comment_blocklist.txt"

# URL: http(s)://... OR bare domain like foo.com/path OR www.foo.com
_URL_RE = re.compile(
    r"(?:https?://\S+)"
    r"|(?:www\.[A-Za-z0-9-]+\.[A-Za-z]{2,}\S*)"
    r"|(?:\b[A-Za-z0-9-]+\.(?:com|net|org|io|co|app|me|ly|xyz|dev|ai|tv|us|uk|de)\b\S*)",
    re.IGNORECASE,
)

# @-mention: @ followed by 1+ word char (IG handles are up to 30)
_MENTION_RE = re.compile(r"(?<!\S)@[A-Za-z0-9_.]{1,30}")

# Email: standard-ish
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Phone number: catches +country, parens-area, 7+ digits with optional separators
_PHONE_RE = re.compile(
    r"(?:(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?:[\s.-]?\d{2,4})?)"
)

_PHONE_MIN_DIGITS = 7

_blocklist_cache: list[str] | None = None


def clear_blocklist_cache() -> None:
    """Drop the cached blocklist so the next call re-reads the file."""
    global _blocklist_cache
    _blocklist_cache = None


def _load_blocklist() -> list[str]:
    global _blocklist_cache
    if _blocklist_cache is not None:
        return _blocklist_cache
    terms: list[str] = []
    try:
        with _BLOCKLIST_PATH.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                terms.append(line.lower())
    except FileNotFoundError:
        terms = []
    _blocklist_cache = terms
    return terms


def _contains_phone(text: str) -> bool:
    for m in _PHONE_RE.finditer(text):
        digits = sum(1 for c in m.group(0) if c.isdigit())
        if digits >= _PHONE_MIN_DIGITS:
            return True
    return False


def check_text(text: str) -> tuple[bool, str | None]:
    """Return (ok, reason). ok=True means the text passes safety."""
    if not text or not text.strip():
        return False, "empty"
    if _EMAIL_RE.search(text):
        return False, "contains_email"
    if _URL_RE.search(text):
        return False, "contains_link"
    if _MENTION_RE.search(text):
        return False, "contains_mention"
    if _contains_phone(text):
        return False, "contains_phone"
    low = text.lower()
    for term in _load_blocklist():
        if term and term in low:
            return False, f"blocklist:{term}"
    return True, None


def filter_safe(candidates: Iterable[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Split candidates into (safe, dropped) where dropped is [(text, reason)]."""
    safe: list[str] = []
    dropped: list[tuple[str, str]] = []
    for c in candidates:
        ok, reason = check_text(c)
        if ok:
            safe.append(c)
        else:
            dropped.append((c, reason or "unknown"))
    return safe, dropped
