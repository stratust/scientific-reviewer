"""Gene verification module for scientific-reviewer.

Validates gene symbols against UniProt and Ensembl databases.
"""

import re
import time
from typing import Any

import httpx

from . import cache

# ── Gene symbol pattern ──────────────────────────────────────────────────

# Matches common gene symbol conventions: starts with uppercase letter(s)
# followed by alphanumeric characters and optional hyphens.
GENE_PATTERN = re.compile(r"\b[A-Z][A-Z0-9-]{0,9}\b")

# ── Skip words ───────────────────────────────────────────────────────────
# Words that match the gene pattern but are common English words or
# domain terms rather than actual gene symbols.

SKIP_WORDS: set[str] = {
    # Articles / determiners / prepositions
    "A",
    "AN",
    "AND",
    "ARE",
    "AS",
    "AT",
    "BE",
    "BUT",
    "BY",
    "CAN",
    "DO",
    "DID",
    "FOR",
    "FROM",
    "HAD",
    "HAS",
    "HAVE",
    "HIS",
    "HOW",
    "IF",
    "IN",
    "INTO",
    "IS",
    "IT",
    "ITS",
    "MAY",
    "NOT",
    "OF",
    "ON",
    "OR",
    "SHE",
    "SO",
    "THE",
    "THEY",
    "THIS",
    "TO",
    "WAS",
    "WERE",
    "WHAT",
    "WHEN",
    "WHERE",
    "WHICH",
    "WHO",
    "WHY",
    "WILL",
    "WITH",
    # Biology / lab terms
    "DNA",
    "RNA",
    "MRNA",
    "TRNA",
    "RRNA",
    "CDNA",
    "SEQ",
    "HUMAN",
    "MOUSE",
    "RAT",
    "YEAST",
    "CELL",
    "CELLS",
    "GENE",
    "GENES",
    "PROTEIN",
    "PROTEINS",
    "DOMAIN",
    "DOMAINS",
    "TYPE",
    "TYPES",
    "ALPHA",
    "BETA",
    "GAMMA",
    "DELTA",
    "EPSILON",
    "ZETA",
    "ETA",
    "THETA",
    "IOTA",
    "KAPPA",
    "LAMBDA",
    "MU",
    "NU",
    "XI",
    "OMICRON",
    "PI",
    "RHO",
    "SIGMA",
    "TAU",
    "UPSILON",
    "PHI",
    "CHI",
    "PSI",
    "OMEGA",
    "TUMOUR",
    "TUMOURS",
    "TUMOR",
    "TUMORS",
    "SUPPRESSOR",
    "SUPPRESSORS",
    "MUTATION",
    "MUTATIONS",
    "MUTATED",
    "MUTANT",
    "MUTANTS",
    "MUTATE",
    "PATHWAY",
    "PATHWAYS",
    "RECEPTOR",
    "RECEPTORS",
    "LIGAND",
    "LIGANDS",
    "KINASE",
    "KINASES",
    "PHOSPHATASE",
    "PHOSPHATASES",
    "TRANSCRIPTION",
    "EXPRESSION",
    "SIGNALING",
    "SIGNALLING",
    "REGULATION",
    "ACTIVATION",
    "INHIBITION",
    "ACTIVITY",
    "FUNCTION",
    "FUNCTIONS",
    "COMPLEX",
    "COMPLEXES",
    "SUBUNIT",
    "SUBUNITS",
    "ISOFORM",
    "ISOFORMS",
    "HOMOLOG",
    "HOMOLOGS",
    "ORTHOLOG",
    "ORTHOLOGS",
    "PARALOG",
    "PARALOGS",
    "VARIANTS",
    "VARIANT",
    "ALLELE",
    "ALLELES",
    "GENOTYPE",
    "GENOTYPES",
    "PHENOTYPE",
    "PHENOTYPES",
    # Common data / computing words
    "DATA",
    "SET",
    "SETS",
    "KEY",
    "MAP",
    "MODE",
    "FILE",
    "CODE",
    "NOTE",
    "NAME",
    "USER",
    "PAGE",
    "LINE",
    "SITE",
    "SIZE",
    "RATE",
    "RANGE",
    "LEVEL",
    "CLASS",
    "GROUP",
    "PART",
    "FORM",
    "CASE",
    "TEXT",
    "VALUE",
    "TARGET",
    "PRIMARY",
    "SECONDARY",
    "TABLE",
    "FIGURE",
    "FIGURES",
    "METHOD",
    "METHODS",
    "RESULT",
    "RESULTS",
    "ANALYSIS",
    "ANALYSES",
    "SAMPLE",
    "SAMPLES",
    "PATIENT",
    "PATIENTS",
    "CONTROL",
    "CONTROLS",
    # General English
    "ALL",
    "ANY",
    "BIG",
    "BOTH",
    "DUE",
    "EACH",
    "ELSE",
    "EVER",
    "FAR",
    "FEW",
    "GET",
    "GOT",
    "HERE",
    "HOT",
    "JUST",
    "KIN",
    "LOT",
    "LOW",
    "MANY",
    "MORE",
    "MOST",
    "MUCH",
    "NEW",
    "NEXT",
    "NONE",
    "NOW",
    "OFF",
    "OLD",
    "ONCE",
    "ONLY",
    "OUT",
    "OVER",
    "PUT",
    "SAY",
    "SEE",
    "SIR",
    "SAME",
    "SOME",
    "STILL",
    "SUCH",
    "THAN",
    "THAT",
    "THEN",
    "THERE",
    "THESE",
    "THOSE",
    "TRY",
    "TWO",
    "UNDER",
    "UPON",
    "VERY",
    "WAY",
    "WELL",
    "YET",
    # Control / quality / methods words
    "POSITIVE",
    "NEGATIVE",
    "STANDARD",
    "NATIVE",
    "AFTER",
    "ALONG",
    "ALSO",
    "ALWAYS",
    "AMONG",
    "AROUND",
    "AWAY",
    "BEFORE",
    "BEHIND",
    "BELOW",
    "ABOVE",
    "ACROSS",
    "AGAINST",
    "VALID",
}

# ── API endpoints ────────────────────────────────────────────────────────

UNIPROT_BASE = "https://rest.uniprot.org"
UNIPROT_SEARCH_URL = f"{UNIPROT_BASE}/uniprotkb/search"
UNIPROT_IDMAPPING_RUN_URL = f"{UNIPROT_BASE}/idmapping/run"
UNIPROT_IDMAPPING_STATUS_URL = f"{UNIPROT_BASE}/idmapping/status"
UNIPROT_IDMAPPING_RESULTS_URL = f"{UNIPROT_BASE}/idmapping/results"

ENSEMBL_BASE = "https://rest.ensembl.org"
ENSEMBL_LOOKUP_URL = f"{ENSEMBL_BASE}/lookup/symbol"
ENSEMBL_XREF_URL = f"{ENSEMBL_BASE}/xrefs/id"

# Taxonomy ID → Ensembl species name
TAX_ID_TO_ENSEMBL_SPECIES: dict[int, str] = {
    9606: "homo_sapiens",
    10090: "mus_musculus",
    10116: "rattus_norvegicus",
    7955: "danio_rerio",
    7227: "drosophila_melanogaster",
    6239: "caenorhabditis_elegans",
    4932: "saccharomyces_cerevisiae",
    3702: "arabidopsis_thaliana",
    284812: "schizosaccharomyces_pombe",
    9615: "canis_lupus_familiaris",
    9913: "bos_taurus",
    9823: "sus_scrofa",
    9031: "gallus_gallus",
    9544: "macaca_mulatta",
    9598: "pan_troglodytes",
    9601: "pongo_abelii",
    9986: "oryctolagus_cuniculus",
    10141: "cavia_porcellus",
    9685: "felis_catus",
    9796: "equus_caballus",
    9940: "ovis_aries",
    9646: "ailuropoda_melanoleuca",
}

HTTP_TIMEOUT: float = 30.0
MAX_RETRIES: int = 2


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_ensembl_species(tax_id: int) -> str:
    """Get the Ensembl species name for a given NCBI taxonomy ID.

    Args:
        tax_id: NCBI taxonomy ID.

    Returns:
        Ensembl species string (e.g., ``"homo_sapiens"``).
    """
    return TAX_ID_TO_ENSEMBL_SPECIES.get(tax_id, f"taxon_{tax_id}")


def _make_request(
    url: str,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    json_data: dict[str, Any] | None = None,
) -> httpx.Response | None:
    """Make an HTTP request with retry and timeout handling.

    Args:
        url: Request URL.
        params: Query parameters (for GET requests).
        method: HTTP method (``"GET"`` or ``"POST"``).
        json_data: JSON body (for POST requests).

    Returns:
        :class:`httpx.Response` on success, or ``None`` on failure.
    """
    for attempt in range(MAX_RETRIES):
        try:
            with httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT)) as client:
                headers = {"Accept": "application/json"}
                if method == "GET":
                    resp = client.get(url, params=params, headers=headers)
                else:
                    resp = client.post(url, json=json_data, headers=headers)
                resp.raise_for_status()
                return resp
        except httpx.TimeoutException:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(1)
        except httpx.HTTPStatusError as exc:
            # 404 is definitive — no retry needed
            if exc.response.status_code == 404:
                return None
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(1)
        except httpx.RequestError:
            if attempt == MAX_RETRIES - 1:
                return None
            time.sleep(1)
    return None


# ── UniProt helpers ──────────────────────────────────────────────────────


def _uniprot_search(symbol: str, tax_id: int) -> dict[str, Any] | None:
    """Search UniProtKB (reviewed entries only) for a gene symbol.

    Args:
        symbol: Gene symbol (e.g., ``"TP53"``).
        tax_id: NCBI taxonomy ID.

    Returns:
        The first result entry, or ``None`` if not found.
    """
    params: dict[str, Any] = {
        "query": f"gene:{symbol} AND organism_id:{tax_id} AND reviewed:true",
        "fields": "accession,gene_names,protein_name,go,go_id,cc_function",
        "size": 5,
    }
    resp = _make_request(UNIPROT_SEARCH_URL, params=params)
    if resp is None:
        return None
    try:
        data = resp.json()
        results = data.get("results", [])
        if results:
            return results[0]
    except (ValueError, KeyError, IndexError):
        pass
    return None


def _extract_protein_name(entry: dict[str, Any]) -> str:
    """Extract the recommended protein name from a UniProt entry."""
    try:
        return entry["proteinDescription"]["recommendedName"]["fullName"]["value"]
    except (KeyError, TypeError):
        pass
    try:
        return (
            entry.get("proteinDescription", {})
            .get("submissionNames", [{}])[0]
            .get("fullName", {})
            .get("value", "")
        )
    except (KeyError, IndexError):
        pass
    return ""


def _extract_go_terms(entry: dict[str, Any]) -> list[str]:
    """Extract GO term identifiers from a UniProt entry.

    The UniProt search response includes GO annotations in a
    ``goAnnotations`` array when the ``go`` or ``go_id`` fields
    are requested.
    """
    go_terms: list[str] = []
    for ann in entry.get("goAnnotations", []):
        go_id = ann.get("goId", "")
        if go_id:
            go_terms.append(go_id)
    return go_terms


def _find_suggestions(symbol: str, tax_id: int, max_results: int = 10) -> list[str]:
    """Find suggested gene symbols for an invalid / ambiguous symbol.

    Performs a broader UniProt text search to identify related
    gene symbols.

    Args:
        symbol: The attempted gene symbol.
        tax_id: NCBI taxonomy ID.
        max_results: Maximum number of suggestions to return.

    Returns:
        List of suggested gene symbols.
    """
    suggestions: list[str] = []

    # Broader text search (not limited to gene: field)
    params: dict[str, Any] = {
        "query": f"({symbol}) AND organism_id:{tax_id} AND reviewed:true",
        "fields": "accession,gene_names",
        "size": max_results,
    }
    resp = _make_request(UNIPROT_SEARCH_URL, params=params)
    if resp is not None:
        try:
            data = resp.json()
            for result in data.get("results", []):
                for gene in result.get("genes", []):
                    name = gene.get("geneName", {}).get("value", "")
                    if name and name.upper() != symbol.upper():
                        suggestions.append(name)
        except (ValueError, KeyError):
            pass

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return unique[:max_results]


def _id_mapping_suggestions(symbol: str, tax_id: int) -> list[str]:
    """Use the UniProt ID mapping API to find suggestions.

    This is a fallback for cases where the text search also
    returns nothing.

    Args:
        symbol: The attempted gene symbol.
        tax_id: NCBI taxonomy ID.

    Returns:
        List of suggested gene symbols.
    """
    try:
        with httpx.Client(timeout=httpx.Timeout(HTTP_TIMEOUT)) as client:
            # Submit mapping job
            resp = client.post(
                UNIPROT_IDMAPPING_RUN_URL,
                json={
                    "from": "Gene_Name",
                    "to": "UniProtKB",
                    "ids": [symbol],
                    "taxId": tax_id,
                },
            )
            resp.raise_for_status()
            job_id = resp.json().get("jobId", "")
            if not job_id:
                return []

            # Poll for completion (up to ~10 s)
            for _ in range(10):
                time.sleep(1)
                status_resp = client.get(
                    f"{UNIPROT_IDMAPPING_STATUS_URL}/{job_id}"
                )
                if status_resp.status_code != 200:
                    continue
                if status_resp.json().get("jobStatus") == "FINISHED":
                    break
            else:
                return []

            # Fetch results
            results_resp = client.get(
                f"{UNIPROT_IDMAPPING_RESULTS_URL}/{job_id}"
            )
            if results_resp.status_code != 200:
                return []

            results_data = results_resp.json()
            suggestions: set[str] = set()
            for mapping in results_data.get("results", []):
                to_entry = mapping.get("to")
                if isinstance(to_entry, dict):
                    for gene in to_entry.get("genes", []):
                        name = gene.get("geneName", {}).get("value", "")
                        if name and name.upper() != symbol.upper():
                            suggestions.add(name)
            return list(suggestions)[:10]
    except Exception:
        return []


# ── Ensembl helpers ──────────────────────────────────────────────────────


def _ensembl_lookup(symbol: str, tax_id: int) -> dict[str, Any] | None:
    """Look up a gene symbol in the Ensembl REST API.

    Args:
        symbol: Gene symbol.
        tax_id: NCBI taxonomy ID.

    Returns:
        Ensembl gene entry, or ``None`` if not found.
    """
    species = _get_ensembl_species(tax_id)
    url = f"{ENSEMBL_LOOKUP_URL}/{species}/{symbol}"
    params = {"content-type": "application/json"}
    resp = _make_request(url, params=params)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def _ensembl_get_go_terms(gene_id: str) -> list[str]:
    """Retrieve GO terms from Ensembl xrefs for a given gene ID.

    Args:
        gene_id: Ensembl gene stable ID (e.g., ``"ENSG00000141510"``).

    Returns:
        List of GO identifiers.
    """
    url = f"{ENSEMBL_XREF_URL}/{gene_id}"
    params = {"content-type": "application/json", "dbname": "GO"}
    resp = _make_request(url, params=params)
    if resp is None:
        return []
    try:
        data = resp.json()
        return [entry["primary_id"] for entry in data if entry.get("primary_id", "").startswith("GO:")]
    except (ValueError, KeyError, TypeError):
        return []


# ── Internal verification logic ──────────────────────────────────────────


def _verify_gene_impl(symbol: str, tax_id: int) -> dict[str, Any]:
    """Core verification implementation.

    Args:
        symbol: Gene symbol.
        tax_id: NCBI taxonomy ID.

    Returns:
        Verification result dict.
    """
    issues: list[str] = []
    suggestions: list[str] = []

    # Step 1 — Search UniProt
    uniprot_entry = _uniprot_search(symbol, tax_id)

    if uniprot_entry is None:
        # Gene not found — look for suggestions
        suggestions = _find_suggestions(symbol, tax_id)
        if not suggestions:
            suggestions = _id_mapping_suggestions(symbol, tax_id)
        return {
            "symbol": symbol,
            "valid": False,
            "uniprot_accession": "",
            "uniprot_name": "",
            "gene_id": "",
            "location": "",
            "description": "",
            "go_terms": [],
            "suggestions": suggestions,
            "issues": [
                f"Gene symbol '{symbol}' not found in UniProt for "
                f"tax ID {tax_id}."
            ],
        }

    # Step 2 — Extract UniProt data
    accession = uniprot_entry.get("primaryAccession", "")
    protein_name = _extract_protein_name(uniprot_entry)
    go_terms = _extract_go_terms(uniprot_entry)

    # Step 3 — Look up Ensembl
    gene_id = ""
    location = ""
    description = ""

    ensembl_entry = _ensembl_lookup(symbol, tax_id)
    if ensembl_entry is not None:
        gene_id = ensembl_entry.get("id", "")
        seq_region = ensembl_entry.get("seq_region_name", "")
        start = ensembl_entry.get("start", 0)
        end = ensembl_entry.get("end", 0)
        strand = ensembl_entry.get("strand", 0)
        location = f"{seq_region}:{start}-{end}:{strand}"
        description = ensembl_entry.get("description", "")
    else:
        issues.append(f"Could not find '{symbol}' in Ensembl.")

    # Step 4 — Augment GO terms from Ensembl if UniProt didn't provide them
    if not go_terms and gene_id:
        go_terms = _ensembl_get_go_terms(gene_id)

    return {
        "symbol": symbol,
        "valid": True,
        "uniprot_accession": accession,
        "uniprot_name": protein_name,
        "gene_id": gene_id,
        "location": location,
        "description": description,
        "go_terms": go_terms,
        "suggestions": [],
        "issues": issues,
    }


# ── Public API ───────────────────────────────────────────────────────────


def extract_gene_symbols(text: str) -> list[str]:
    """Extract potential gene symbols from text using regex.

    Uses :data:`GENE_PATTERN` to identify candidate symbols and filters
    out entries in :data:`SKIP_WORDS`.  Returns unique symbols in order
    of first appearance.

    Args:
        text: Input text to scan.

    Returns:
        List of unique gene symbol candidates.
    """
    matches = GENE_PATTERN.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        upper = m.upper()
        if upper not in SKIP_WORDS and upper not in seen:
            seen.add(upper)
            result.append(upper)
    return result


def verify_gene(symbol: str, tax_id: int = 9606) -> dict[str, Any]:
    """Verify a single gene symbol against UniProt and Ensembl.

    Looks up the symbol in UniProtKB (reviewed entries only) and
    Ensembl, returning accession numbers, genomic location,
    description, and GO terms.

    Results are cached to avoid redundant API calls.

    Args:
        symbol: Gene symbol to verify (e.g., ``"TP53"``, ``"BRCA1"``).
        tax_id: NCBI taxonomy ID (default ``9606`` for human).

    Returns:
        A dict with the following keys:

        - ``symbol`` – the input gene symbol.
        - ``valid`` – whether the symbol was found in UniProt.
        - ``uniprot_accession`` – primary UniProtKB accession.
        - ``uniprot_name`` – recommended protein name.
        - ``gene_id`` – Ensembl gene stable ID.
        - ``location`` – genomic location (``chr:start-end:strand``).
        - ``description`` – gene description from Ensembl.
        - ``go_terms`` – list of Gene Ontology identifiers.
        - ``suggestions`` – suggested corrections for invalid symbols.
        - ``issues`` – list of warnings / error messages.
    """
    cache_key = f"gene:{symbol}:{tax_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _verify_gene_impl(symbol, tax_id)
    cache.set(cache_key, result)
    return result


def verify_genes(symbols: list[str], tax_id: int = 9606) -> list[dict[str, Any]]:
    """Verify multiple gene symbols.

    Calls :func:`verify_gene` for each symbol in the input list.

    Args:
        symbols: List of gene symbols to verify.
        tax_id: NCBI taxonomy ID (default ``9606``).

    Returns:
        List of verification result dicts, one per input symbol.
    """
    return [verify_gene(s, tax_id) for s in symbols]


def verify_text(text: str, tax_id: int = 9606) -> dict[str, Any]:
    """Extract gene symbols from text, verify them, and return annotations.

    Uses :func:`extract_gene_symbols` to identify candidates, verifies
    each with :func:`verify_gene`, and wraps valid symbols in ``**bold**``
    markers and invalid symbols in ``~~strikethrough~~`` markers.

    Args:
        text: Scientific text to analyse.
        tax_id: NCBI taxonomy ID (default ``9606``).

    Returns:
        A dict with:

        - ``text`` – annotated copy of the input text.
        - ``results`` – verification results for each found symbol.
        - ``found_count`` – number of symbols found.
    """
    symbols = extract_gene_symbols(text)
    results = verify_genes(symbols, tax_id)

    # Build annotation map
    valid: set[str] = {r["symbol"] for r in results if r["valid"]}
    invalid: set[str] = {r["symbol"] for r in results if not r["valid"]}

    # Replace longer symbols first to avoid substring conflicts
    annotated = text
    for sym in sorted(valid | invalid, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(sym)}\b")
        if sym in valid:
            annotated = pattern.sub(f"**{sym}**", annotated)
        else:
            annotated = pattern.sub(f"~~{sym}~~", annotated)

    return {
        "text": annotated,
        "results": results,
        "found_count": len(results),
    }
