"""Tests for the gene verification module."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from scientific_reviewer import cache
from scientific_reviewer.gene import (
    SKIP_WORDS,
    extract_gene_symbols,
    verify_gene,
    verify_genes,
    verify_text,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the in-memory cache before each test."""
    cache.clear()


def _mock_response(status_code: int = 200, json_data: Any = None) -> httpx.Response:
    """Build a mock :class:`httpx.Response`."""
    resp = httpx.Response(status_code=status_code, json=json_data)
    return resp


def _make_mock_request(return_value: httpx.Response | None = None):
    """Factory that returns a mock *make_request that always returns *return_value*."""
    return patch(
        "scientific_reviewer.gene._make_request",
        return_value=return_value,
    )


# ── Helpers: sample UniProt / Ensembl responses ─────────────────────────


SAMPLE_UNIPROT_TP53 = {
    "results": [
        {
            "primaryAccession": "P04637",
            "uniProtkbId": "P53_HUMAN",
            "genes": [{"geneName": {"value": "TP53"}}],
            "proteinDescription": {
                "recommendedName": {
                    "fullName": {"value": "Cellular tumor antigen p53"},
                },
            },
            "goAnnotations": [
                {"goId": "GO:0005737", "geneOntologyId": "GO:0005737"},
                {"goId": "GO:0002039", "geneOntologyId": "GO:0002039"},
            ],
        }
    ]
}

SAMPLE_UNIPROT_BRCA1 = {
    "results": [
        {
            "primaryAccession": "P38398",
            "uniProtkbId": "BRCA1_HUMAN",
            "genes": [{"geneName": {"value": "BRCA1"}}],
            "proteinDescription": {
                "recommendedName": {
                    "fullName": {"value": "Breast cancer type 1 susceptibility protein"},
                },
            },
            "goAnnotations": [
                {"goId": "GO:0005634", "geneOntologyId": "GO:0005634"},
            ],
        }
    ]
}

SAMPLE_UNIPROT_EMPTY = {"results": []}

SAMPLE_ENSEMBL_TP53 = {
    "id": "ENSG00000141510",
    "display_name": "TP53",
    "description": "tumor protein p53 [Source:HGNC Symbol;Acc:HGNC:11998]",
    "seq_region_name": "17",
    "start": 7661779,
    "end": 7687546,
    "strand": -1,
    "biotype": "protein_coding",
    "assembly_name": "GRCh38",
}

SAMPLE_ENSEMBL_BRCA1 = {
    "id": "ENSG00000012048",
    "display_name": "BRCA1",
    "description": "BRCA1 DNA repair associated [Source:HGNC Symbol;Acc:HGNC:1100]",
    "seq_region_name": "17",
    "start": 43044295,
    "end": 43170245,
    "strand": 1,
    "biotype": "protein_coding",
    "assembly_name": "GRCh38",
}

SAMPLE_SUGGESTIONS = {
    "results": [
        {
            "primaryAccession": "P38398",
            "genes": [{"geneName": {"value": "BRCA1"}}],
        },
        {
            "primaryAccession": "P51587",
            "genes": [{"geneName": {"value": "BRCA2"}}],
        },
    ]
}


# ── extract_gene_symbols ────────────────────────────────────────────────


class TestExtractGeneSymbols:
    def test_basic_extraction(self) -> None:
        """Recognise common gene symbols in plain text."""
        text = "Mutations in TP53 and BRCA1 genes."
        assert extract_gene_symbols(text) == ["TP53", "BRCA1"]

    def test_deduplicates(self) -> None:
        """Duplicate symbols should appear only once."""
        text = "TP53 is a key tumour suppressor. TP53 is another tumour suppressor."
        assert extract_gene_symbols(text) == ["TP53"]

    def test_skip_words_are_filtered(self) -> None:
        """Common English words matching the pattern must be excluded."""
        text = "The DNA and RNA levels were measured in the CELL line."
        result = extract_gene_symbols(text)
        for word in ("THE", "DNA", "RNA", "CELL"):
            assert word not in result

    def test_skip_words_contains_expected_terms(self) -> None:
        """Verify a representative subset of SKIP_WORDS exists."""
        for word in ("DNA", "RNA", "THE", "AND", "FOR", "ALPHA", "BETA"):
            assert word in SKIP_WORDS

    def test_empty_text(self) -> None:
        """Empty input yields an empty list."""
        assert extract_gene_symbols("") == []

    def test_text_without_symbols(self) -> None:
        """Text that contains only skip words returns nothing."""
        assert extract_gene_symbols("The DNA and RNA data.") == []

    def test_symbol_with_hyphen(self) -> None:
        """Gene symbols with hyphens are captured."""
        text = "HLA-DRB1 is associated with autoimmune disease."
        assert "HLA-DRB1" in extract_gene_symbols(text)

    def test_case_sensitive(self) -> None:
        """Gene symbols with lowercase letters are not extracted."""
        text = "tp53 gene expression levels."
        assert extract_gene_symbols(text) == []

    def test_order_preserved(self) -> None:
        """Symbols appear in the order they were first seen."""
        text = "EGFR TP53 BRCA1 EGFR also."
        assert extract_gene_symbols(text) == ["EGFR", "TP53", "BRCA1"]


# ── verify_gene ─────────────────────────────────────────────────────────


class TestVerifyGene:
    def test_valid_human_gene(self) -> None:
        """Successfully verify a real human gene symbol (TP53)."""
        with _make_mock_request() as mock_request:
            # First call: UniProt search (returns TP53)
            # Second call: Ensembl lookup (returns TP53)
            mock_request.side_effect = [
                _mock_response(json_data=SAMPLE_UNIPROT_TP53),
                _mock_response(json_data=SAMPLE_ENSEMBL_TP53),
            ]

            result = verify_gene("TP53")

        assert result["symbol"] == "TP53"
        assert result["valid"] is True
        assert result["uniprot_accession"] == "P04637"
        assert result["uniprot_name"] == "Cellular tumor antigen p53"
        assert result["gene_id"] == "ENSG00000141510"
        assert result["location"] == "17:7661779-7687546:-1"
        assert "tumor protein p53" in result["description"]
        assert "GO:0005737" in result["go_terms"]
        assert "GO:0002039" in result["go_terms"]
        assert result["suggestions"] == []
        assert result["issues"] == []

    def test_uses_cache(self) -> None:
        """Second call with the same symbol should hit the cache."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data=SAMPLE_UNIPROT_TP53),
                _mock_response(json_data=SAMPLE_ENSEMBL_TP53),
            ]

            # First call — makes real API requests
            r1 = verify_gene("TP53")
            # Second call — should use cache, no additional API calls
            r2 = verify_gene("TP53")

        assert r1 == r2
        # Only 2 calls (UniProt + Ensembl) not 4
        assert mock_request.call_count == 2

    def test_invalid_symbol(self) -> None:
        """An unrecognised symbol returns valid=False with issues."""
        with _make_mock_request() as mock_request:
            # UniProt search returns nothing, suggestion search also empty
            mock_request.side_effect = [
                _mock_response(json_data=SAMPLE_UNIPROT_EMPTY),  # exact search
                _mock_response(json_data=SAMPLE_UNIPROT_EMPTY),  # suggestion search
            ]

            result = verify_gene("ZZZZZ")

        assert result["symbol"] == "ZZZZZ"
        assert result["valid"] is False
        assert result["uniprot_accession"] == ""
        assert result["issues"] != []

    def test_ambiguous_symbol_suggests_corrections(self) -> None:
        """An ambiguous symbol like 'BRCA' should yield suggestions."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                # exact UniProt search — returns nothing (BRCA alone isn't a gene)
                _mock_response(json_data=SAMPLE_UNIPROT_EMPTY),
                # broader suggestion search — returns BRCA1, BRCA2
                _mock_response(json_data=SAMPLE_SUGGESTIONS),
            ]

            result = verify_gene("BRCA")

        assert result["valid"] is False
        assert "BRCA1" in result["suggestions"]
        assert "BRCA2" in result["suggestions"]

    def test_ensembl_unavailable(self) -> None:
        """Gene is found in UniProt but not Ensembl — partial result."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data=SAMPLE_UNIPROT_TP53),  # UniProt: OK
                None,  # Ensembl: not found / error
            ]

            result = verify_gene("TP53")

        assert result["valid"] is True
        assert result["uniprot_accession"] == "P04637"
        assert result["gene_id"] == ""  # Ensembl data missing
        assert "Could not find" in result["issues"][0]

    def test_http_timeout(self) -> None:
        """HTTP timeouts are handled gracefully."""
        with _make_mock_request() as mock_request:
            # Both UniProt calls time out
            mock_request.side_effect = [
                None,  # uniprot_search
                None,  # suggestion search
            ]

            result = verify_gene("TIMEOUT")

        assert result["valid"] is False
        assert result["symbol"] == "TIMEOUT"

    def test_different_tax_id(self) -> None:
        """Look up a mouse gene (tax ID 10090)."""
        sample_mouse = {
            "results": [
                {
                    "primaryAccession": "P02340",
                    "genes": [{"geneName": {"value": "Trp53"}}],
                    "proteinDescription": {
                        "recommendedName": {
                            "fullName": {"value": "Cellular tumor antigen p53"},
                        },
                    },
                    "goAnnotations": [{"goId": "GO:0005737"}],
                }
            ]
        }
        sample_ensembl_mouse = {
            "id": "ENSMUSG00000059552",
            "seq_region_name": "11",
            "start": 69580973,
            "end": 69593000,
            "strand": -1,
            "description": "transformation related protein 53 [Source:MGI Symbol;Acc:MGI:98834]",
        }

        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data=sample_mouse),
                _mock_response(json_data=sample_ensembl_mouse),
            ]

            result = verify_gene("Trp53", tax_id=10090)

        assert result["symbol"] == "Trp53"
        assert result["valid"] is True
        assert result["uniprot_accession"] == "P02340"
        assert result["gene_id"] == "ENSMUSG00000059552"
        assert result["location"] == "11:69580973-69593000:-1"


# ── verify_genes ────────────────────────────────────────────────────────


class TestVerifyGenes:
    def test_multiple_symbols(self) -> None:
        """Verifying multiple symbols returns one result per symbol."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                # TP53 UniProt
                _mock_response(json_data=SAMPLE_UNIPROT_TP53),
                # TP53 Ensembl
                _mock_response(json_data=SAMPLE_ENSEMBL_TP53),
                # BRCA1 UniProt
                _mock_response(json_data=SAMPLE_UNIPROT_BRCA1),
                # BRCA1 Ensembl
                _mock_response(json_data=SAMPLE_ENSEMBL_BRCA1),
            ]

            results = verify_genes(["TP53", "BRCA1"])

        assert len(results) == 2
        assert results[0]["symbol"] == "TP53"
        assert results[0]["valid"] is True
        assert results[1]["symbol"] == "BRCA1"
        assert results[1]["valid"] is True

    def test_empty_list(self) -> None:
        """An empty list returns an empty list."""
        assert verify_genes([]) == []


# ── verify_text ─────────────────────────────────────────────────────────


class TestVerifyText:
    def test_annotates_valid_symbols(self) -> None:
        """Valid symbols are wrapped in **bold** markers."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data=SAMPLE_UNIPROT_TP53),  # TP53 UniProt
                _mock_response(json_data=SAMPLE_ENSEMBL_TP53),  # TP53 Ensembl
            ]

            result = verify_text("TP53 is a tumour suppressor.")

        assert "**TP53**" in result["text"]
        assert result["found_count"] == 1
        assert len(result["results"]) == 1

    def test_annotates_invalid_symbols(self) -> None:
        """Invalid symbols are wrapped in ~~strikethrough~~ markers."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data=SAMPLE_UNIPROT_EMPTY),  # exact
                _mock_response(json_data=SAMPLE_SUGGESTIONS),  # suggestions
            ]

            result = verify_text("BRCA is not a valid gene symbol.")

        assert "~~BRCA~~" in result["text"]
        assert len(result["results"]) == 1
        assert result["results"][0]["valid"] is False

    def test_mixed_valid_and_invalid(self) -> None:
        """Both valid and invalid markers appear in the text."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                # TP53 UniProt
                _mock_response(json_data=SAMPLE_UNIPROT_TP53),
                # TP53 Ensembl
                _mock_response(json_data=SAMPLE_ENSEMBL_TP53),
                # ZZZZZ UniProt
                _mock_response(json_data=SAMPLE_UNIPROT_EMPTY),
                # ZZZZZ suggestions
                _mock_response(json_data=SAMPLE_UNIPROT_EMPTY),
            ]

            result = verify_text("TP53 and ZZZZZ.")

        assert "**TP53**" in result["text"]
        assert "~~ZZZZZ~~" in result["text"]

    def test_empty_text(self) -> None:
        """Empty text yields no annotations."""
        result = verify_text("")
        assert result["text"] == ""
        assert result["found_count"] == 0
        assert result["results"] == []

    def test_only_skip_words(self) -> None:
        """Text with only skip words yields no annotations."""
        result = verify_text("The DNA and RNA.")
        assert result["found_count"] == 0
        assert result["results"] == []


# ── Edge cases / error handling ─────────────────────────────────────────


class TestErrorHandling:
    def test_gene_returned_as_non_dict(self) -> None:
        """Handle malformed UniProt entries gracefully."""
        malformed = {
            "results": [
                {
                    "primaryAccession": "P04637",
                    # no 'genes' key — shouldn't crash
                    "proteinDescription": {"recommendedName": {"fullName": {"value": "X"}}},
                    "goAnnotations": [],
                }
            ]
        }
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data=malformed),       # UniProt search
                _mock_response(json_data=SAMPLE_ENSEMBL_TP53),  # Ensembl lookup
                _mock_response(json_data=[]),              # Ensembl xrefs (GO fallback)
            ]

            result = verify_gene("TP53")
        # Should not raise — the gene list is absent but code handles it
        assert result["valid"] is True
        assert result["uniprot_accession"] == "P04637"

    def test_uniprot_returns_no_results_key(self) -> None:
        """UniProt response missing 'results' key."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data={}),  # empty object
                _mock_response(json_data=SAMPLE_UNIPROT_EMPTY),
            ]

            result = verify_gene("GHOST")
        assert result["valid"] is False

    def test_ensembl_http_404(self) -> None:
        """Ensembl 404 is handled without raising."""
        with _make_mock_request() as mock_request:
            mock_request.side_effect = [
                _mock_response(json_data=SAMPLE_UNIPROT_TP53),
                None,  # Ensembl returns None (simulating 404)
            ]

            result = verify_gene("TP53")
        assert result["valid"] is True
        assert result["gene_id"] == ""

    def test_httpx_transport_error(self) -> None:
        """A transport-level error (connection refused) is handled."""
        with patch(
            "scientific_reviewer.gene._make_request", return_value=None
        ):
            result = verify_gene("OFFLINE")
        assert result["valid"] is False
        assert result["symbol"] == "OFFLINE"
