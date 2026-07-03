"""Citation verification using the NCBI E-utilities API.

Provides ``verify_pmid`` and ``verify_pmids`` to look up PubMed identifiers
and return structured citation data with formatted references.
Results are cached via :mod:`scientific_reviewer.cache` to avoid redundant
network calls.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from scientific_reviewer.cache import get as cache_get
from scientific_reviewer.cache import set as cache_set

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ESUMMARY_URL = f"{BASE_URL}/esummary.fcgi"
EFETCH_URL = f"{BASE_URL}/efetch.fcgi"

# NCBI asks that you identify yourself — change via verify_pmid(…, email=…).
DEFAULT_EMAIL = "scientific-reviewer@example.com"

# Throttle: 3 requests per second max (NCBI guideline).
_REQUEST_INTERVAL = 0.35  # seconds
_last_request: float = 0.0

_MAX_RETRIES = 3
_BACKOFF = 1.0  # initial backoff seconds


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _throttle() -> None:
    """Pause if needed to honour NCBI's rate limit (~3 req/s)."""
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < _REQUEST_INTERVAL:
        time.sleep(_REQUEST_INTERVAL - elapsed)
    _last_request = time.monotonic()


def _maybe_int(value: Any) -> int | None:
    """Safely coerce a value to int, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _maybe_str(value: Any, default: str = "") -> str:
    """Safely coerce a value to str."""
    if value is None:
        return default
    return str(value)


def _extract_article_id(article_ids: list[dict], idtype: str) -> str:
    """Extract an article ID of a given type from the esummary articleids list."""
    for item in article_ids or []:
        if isinstance(item, dict) and item.get("idtype") == idtype:
            return _maybe_str(item.get("value"))
    return ""


def _build_apa_citation(
    authors: list[str],
    year: int | None,
    title: str,
    journal: str,
    pmid: str,
) -> str:
    """Build an APA-style citation string."""
    author_part = _format_authors_apa(authors)
    year_part = f"({year})" if year else "(n.d.)"
    return f"{author_part} {year_part}. {title}. *{journal}*. PMID: {pmid}"


def _build_bibtex_citation(
    authors: list[str],
    year: int | None,
    title: str,
    journal: str,
    pmid: str,
    doi: str,
) -> str:
    """Build a BibTeX entry string."""
    key = f"PMID:{pmid}"
    author_str = " and ".join(authors) if authors else "Unknown"
    year_str = str(year) if year else "n.d."
    fields = [
        f"  author = {{{author_str}}}",
        f"  title = {{{title}}}",
        f"  journal = {{{journal}}}",
        f"  year = {{{year_str}}}",
        f"  pmid = {{{pmid}}}",
    ]
    if doi:
        fields.append(f"  doi = {{{doi}}}")
    return "@article{" + key + ",\n" + ",\n".join(fields) + "\n}\n"


def _format_authors_apa(authors: list[str]) -> str:
    """Format a list of author names into APA style.

    Handles both ``"LastName FM"`` (NCBI esummary) and plain name formats.
    """
    if not authors:
        return "Unknown"

    formatted = []
    for name in authors[:6]:  # APA: list up to 6 authors
        name = name.strip()
        parts = name.split(", ")
        if len(parts) == 2:
            last, first_middle = parts
            initials = " ".join(f"{c[0]}." for c in first_middle.split() if c)
            formatted.append(f"{last}, {initials}")
        else:
            formatted.append(name)

    if len(authors) > 6:
        formatted.append("…")

    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} & {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"


def _parse_efetch_abstract(xml_text: str) -> str:
    """Extract a plain-text abstract snippet from NCBI efetch XML."""
    # Simple XML parsing: extract <AbstractText> content
    matches = re.findall(
        r"<AbstractText[^>]*>(.*?)</AbstractText>",
        xml_text,
        re.DOTALL,
    )
    if not matches:
        return ""

    # Join multiple paragraphs, strip XML/HTML tags
    parts = []
    for m in matches:
        clean = re.sub(r"<[^>]+>", "", m)
        clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            parts.append(clean)

    snippet = " ".join(parts)
    if len(snippet) > 500:
        snippet = snippet[:497] + "…"
    return snippet


def _call_esummary(
    pmid: str,
    client: httpx.Client,
    email: str,
) -> dict[str, Any]:
    """Fetch esummary JSON for a single PMID.

    Returns the parsed result dict, or an empty dict on failure.
    """
    _throttle()
    params: dict[str, str] = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "json",
        "email": email,
    }
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.get(ESUMMARY_URL, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            uids = result.get("uids", [])
            if not uids:
                return {}  # PMID not found
            uid = result.get(str(pmid)) or result.get(uids[0])
            return dict(uid) if uid else {}
        except httpx.HTTPError as exc:
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF * attempt)
                continue
            return {"_error": f"HTTP error: {exc}"}
        except (KeyError, ValueError, IndexError) as exc:
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF * attempt)
                continue
            return {"_error": f"Parse error: {exc}"}
    return {}


def _call_efetch(
    pmid: str,
    client: httpx.Client,
    email: str,
) -> str:
    """Fetch efetch XML for a single PMID (abstract text).

    Returns the raw XML text, or an empty string on failure.
    """
    _throttle()
    params: dict[str, str] = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
        "rettype": "abstract",
        "email": email,
    }
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.get(EFETCH_URL, params=params, timeout=30.0)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError:
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF * attempt)
                continue
            return ""
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_pmid(
    pmid: str,
    *,
    email: str = DEFAULT_EMAIL,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Verify a single PubMed ID and return structured citation data.

    Results are cached locally so repeated lookups of the same PMID are
    instant. Network errors are captured in the ``issues`` list rather
    than raised.

    Parameters:
        pmid:  PubMed ID (numeric string, e.g. ``"23193287"``).
        email:  Email sent to NCBI for API tracking (optional).
        client: Optional shared ``httpx.Client``.  A new one is created
                per call if not supplied.

    Returns:
        A dict with the following keys:

        - **pmid** — the input PMID
        - **exists** — whether the PMID was found
        - **title** — article title
        - **authors** — list of author name strings
        - **journal** — journal name
        - **year** — publication year
        - **doi** — DOI string
        - **pmcid** — PubMed Central ID
        - **citations** — ``{"apa": str, "bibtex": str}``
        - **abstract_snippet** — first ~500 chars of the abstract
        - **issues** — list of warning / error strings
    """
    # Default empty result
    empty: dict[str, Any] = {
        "pmid": pmid,
        "exists": False,
        "title": "",
        "authors": [],
        "journal": "",
        "year": None,
        "doi": "",
        "pmcid": "",
        "citations": {"apa": "", "bibtex": ""},
        "abstract_snippet": "",
        "issues": [],
    }

    # Check cache first
    cached = cache_get(f"pmid:{pmid}")
    if cached is not None:
        return dict(cached)

    own_client = client is None
    if own_client:
        client = httpx.Client()

    try:
        summary = _call_esummary(pmid, client, email)

        # Detect non-existent PMID
        if not summary or "_error" in summary:
            result = dict(empty)
            if summary and "_error" in summary:
                result["issues"].append(f"Network error: {summary['_error']}")
            else:
                result["issues"].append("PMID not found")
            cache_set(f"pmid:{pmid}", result)
            return result

        # Parse fields
        authors_raw: list = summary.get("authors", [])
        authors = []
        for a in authors_raw:
            if isinstance(a, dict):
                name = a.get("name", "")
                if name:
                    authors.append(name)
            elif isinstance(a, str):
                authors.append(a)

        title = _maybe_str(summary.get("title", ""))
        journal = _maybe_str(summary.get("source", "") or summary.get("fulljournalname", ""))
        year = _maybe_int(summary.get("pubdate", "")[:4]) if summary.get("pubdate") else None

        article_ids = summary.get("articleids", [])
        doi = _extract_article_id(article_ids, "doi")
        pmcid = _extract_article_id(article_ids, "pmc")

        # Fetch abstract
        abstract_xml = _call_efetch(pmid, client, email)
        abstract_snippet = _parse_efetch_abstract(abstract_xml)

        # Build citation strings
        apa = _build_apa_citation(authors, year, title, journal, pmid)
        bibtex = _build_bibtex_citation(authors, year, title, journal, pmid, doi)

        result = {
            "pmid": pmid,
            "exists": True,
            "title": title,
            "authors": authors,
            "journal": journal,
            "year": year,
            "doi": doi,
            "pmcid": pmcid,
            "citations": {"apa": apa, "bibtex": bibtex},
            "abstract_snippet": abstract_snippet,
            "issues": [],
        }

        # Cache and return
        cache_set(f"pmid:{pmid}", result)
        return result

    except Exception as exc:
        result = dict(empty)
        result["issues"].append(f"Unexpected error: {exc}")
        return result

    finally:
        if own_client:
            client.close()


def verify_pmids(
    pmids: list[str],
    *,
    email: str = DEFAULT_EMAIL,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Verify a list of PubMed IDs, returning structured data for each.

    PMIDs already in cache are returned immediately; the rest are fetched
    from NCBI with rate limiting.

    Parameters:
        pmids: List of PubMed ID strings.
        email:  Email sent to NCBI for API tracking (optional).
        client: Optional shared ``httpx.Client``.

    Returns:
        A list of dicts (one per PMID) in the same order as *pmids*.
    """
    results: list[dict[str, Any]] = []
    own_client = client is None
    if own_client:
        client = httpx.Client()

    try:
        for pmid in pmids:
            results.append(
                verify_pmid(pmid, email=email, client=client)
            )
        return results
    finally:
        if own_client:
            client.close()
