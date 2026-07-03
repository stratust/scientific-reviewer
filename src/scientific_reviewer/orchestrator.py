"""
Scientific Reviewer — Orchestrator

Multi-agent coordinator that classifies claims, dispatches specialist
reviewers, merges results, and produces a unified verification report.
"""
import re
from datetime import datetime
from typing import Any

from . import cache
from .citation import verify_pmids
from .gene import verify_genes

# Patterns for claim classification
PMID_PATTERN = re.compile(r'(?<!\d)(\d{6,8})(?!\d)')
DOI_PATTERN = re.compile(r'10\.\d{4,}/[-._;()/:A-Za-z0-9]+')
GENE_PATTERN = re.compile(r'\b([A-Z][A-Z0-9]{1,7})\b')
GEO_PATTERN = re.compile(r'\b(GSE\d+|GSM\d+|GDS\d+)\b')
STAT_PATTERN = re.compile(r'(p\s*[<>=]\s*0?\.?\d+|fold.?change\s*[=:]\s*[\d.]+|log2FC\s*[=:]\s*-?[\d.]+)', re.IGNORECASE)

SKIP_WORDS = {
    'THE', 'AND', 'FOR', 'WITH', 'FROM', 'THAT', 'THIS', 'THAN',
    'CELL', 'GENE', 'RNA', 'DNA', 'MHC', 'TCR', 'CDR', 'HIV',
    'DATA', 'FILE', 'TYPE', 'NULL', 'TRUE', 'FALSE', 'NODE',
    'MAIN', 'TEMP', 'NEXT', 'LAST', 'FIRST',
    'TITLE', 'HEAD', 'BODY', 'NAME', 'USER', 'HOME',
    'PMID', 'PMCID', 'DOI', 'GSE', 'GSM', 'GDS', 'GPL',
    'TABLE', 'FIG', 'FIGURE',
    'QC', 'CTRL', 'PATIENT', 'SAMPLE', 'CLONE', 'CLONES',
    'VS', 'VIA', 'GEM', 'BAM', 'FASTQ', 'SRA', 'HPC',
    'MAX', 'MIN', 'AVG', 'SUM', 'TOTAL', 'COUNT',
    'FMRP', 'USP', 'MIT', 'UCSF', 'NIH', 'FDA',
    'RPM', 'RPKM', 'FPKM', 'TPM', 'CPM',
    'HTML', 'CSV', 'TSV', 'JSON', 'YAML', 'TOML',
    'PCA', 'UMAP', 'TSNE', 'SVD',
    'REST', 'API', 'URL', 'URI', 'SSH', 'HTTP', 'HTTPS',
    'VDJ', 'VJ',
    'CHR', 'CHRS', 'BP', 'KB', 'MB', 'GB', 'TB',
    'PCT', 'IDENT', 'RESTING', 'ACTIVATED',
    'TE', 'GEO', 'GEX', 'ZNF', 'JEM', 'NAT', 'SCI', 'PLOS',
    'SRA', 'SRR', 'ENA', 'NCBI', 'UCSC', 'ENSEMBL',
    'BWA', 'STAR',
    'IL', 'CD3', 'CD28', 'CD8',
    'R', 'RAM', 'CPU', 'GPU',
    'UMI', 'UMIS', 'TRG', 'TRD', 'IGH', 'IGL', 'IGK',
    'TRA', 'TRB', 'ID',
}


def classify_claims(text: str) -> dict[str, list[str]]:
    """Classify verifiable claims in text by type.

    Args:
        text: Scientific text to analyze.

    Returns:
        Dictionary with keys: pmids, dois, genes, geo_accessions, statements.
    """
    claims: dict[str, list[str]] = {
        "pmids": [],
        "dois": [],
        "genes": [],
        "geo_accessions": [],
        "statements": [],
    }

    # PMIDs
    already_seen_pmids: set[str] = set()
    for m in PMID_PATTERN.finditer(text):
        pmid = m.group(1)
        if 1990 <= int(pmid) <= 2029:
            continue
        pos = m.start()
        if pos >= 3 and text[pos-3:pos].upper() in ('GSE', 'GSM', 'GDS', 'GPL'):
            continue
        if pos >= 1 and text[pos-1] == 'e':
            continue
        if pmid not in already_seen_pmids:
            already_seen_pmids.add(pmid)
            claims["pmids"].append(pmid)

    # DOIs
    for m in DOI_PATTERN.finditer(text):
        doi = m.group(0)
        if doi not in claims["dois"]:
            claims["dois"].append(doi)

    # Genes
    already_seen_genes: set[str] = set()
    for m in GENE_PATTERN.finditer(text):
        gene = m.group(1)
        if gene in SKIP_WORDS or gene in already_seen_genes:
            continue
        already_seen_genes.add(gene)
        claims["genes"].append(gene)

    # GEO accessions
    for m in GEO_PATTERN.finditer(text):
        acc = m.group(1)
        if acc not in claims["geo_accessions"]:
            claims["geo_accessions"].append(acc)

    # Statistical statements
    for m in STAT_PATTERN.finditer(text):
        stat = m.group(1).rstrip('.,;:!?)')
        if stat not in claims["statements"]:
            claims["statements"].append(stat)

    return claims


def review_text(text: str) -> dict[str, Any]:
    """Run full review pipeline on scientific text.

    Args:
        text: Scientific text to review.

    Returns:
        Full review report with verified claims, issues, and stats.
    """
    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "text_length": len(text),
        "claims_found": {},
        "pmids": [],
        "genes": [],
        "issues": [],
        "corrections": [],
        "confidence": "high",
        "stats": {},
    }

    claims = classify_claims(text)
    report["claims_found"] = {k: len(v) for k, v in claims.items()}

    # Verify citations
    if claims["pmids"]:
        uncached = []
        for pmid in claims["pmids"]:
            cached = cache.get(f"pmid:{pmid}")
            if cached:
                report["pmids"].append(cached)
            else:
                uncached.append(pmid)
        if uncached:
            fresh = verify_pmids(uncached)
            for item in fresh:
                cache.set(f"pmid:{item.get('pmid','')}", item)
            report["pmids"].extend(fresh)

    # Verify genes
    if claims["genes"]:
        uncached = []
        for gene in claims["genes"]:
            cached = cache.get(f"gene:{gene}")
            if cached:
                report["genes"].append(cached)
            else:
                uncached.append(gene)
        if uncached:
            fresh = verify_genes(uncached[:10])
            for item in fresh:
                cache.set(f"gene:{item.get('symbol','')}", item)
            report["genes"].extend(fresh)

    # Collect issues
    issues: list[str] = []
    for c in report["pmids"]:
        if c.get("exists") is False:
            issues.append(f"PMID {c['pmid']}: does not exist in PubMed")
        for iss in c.get("issues", []):
            issues.append(f"PMID {c['pmid']}: {iss}")

    for g in report["genes"]:
        if g.get("valid") is False:
            sugg = g.get("suggestions", [])
            if sugg:
                issues.append(f"Gene {g['symbol']}: ambiguous. Suggestions: {', '.join(sugg[:4])}")
            else:
                issues.append(f"Gene {g['symbol']}: not found in UniProt/Ensembl")
        for iss in g.get("issues", []):
            if "timed out" in iss.lower():
                continue  # Skip timeout noise in summary
            issues.append(f"Gene {g['symbol']}: {iss}")

    # GEO accession info
    if claims["geo_accessions"]:
        for acc in claims["geo_accessions"]:
            issues.append(f"GEO {acc}: accession detected (verify manually at https://ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={acc})")

    report["issues"] = issues
    report["stats"] = {
        "total_verified": len(report["pmids"]) + len(report["genes"]),
        "total_issues": len(issues),
        "verified_pmids": len(report["pmids"]),
        "verified_genes": len(report["genes"]),
    }

    if not issues:
        report["confidence"] = "high"
    elif len(issues) <= 3:
        report["confidence"] = "medium"
    else:
        report["confidence"] = "low"

    return report
