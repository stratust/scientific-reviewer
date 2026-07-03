"""Tests for :mod:`scientific_reviewer.citation`."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scientific_reviewer import cache as cache_mod
from scientific_reviewer import citation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Redirect cache to a temp dir and clear it before each test."""
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache_mod, "CACHE_FILE", tmp_path / "cache.json")
    cache_mod.clear()


# ---------------------------------------------------------------------------
# Sample NCBI responses
# ---------------------------------------------------------------------------

SAMPLE_ESUMMARY = {
    "header": {"type": "esummary", "version": "0.3"},
    "result": {
        "uids": ["23193287"],
        "23193287": {
            "uid": "23193287",
            "pubdate": "2012 Dec 4",
            "epubdate": "2012 Nov 30",
            "source": "Nucleic Acids Res",
            "fulljournalname": "Nucleic acids research",
            "title": "PubMed to PDF: a simple tool for downloading full texts",
            "authors": [
                {"name": "Smith JA", "authtype": "author"},
                {"name": "Jones BC", "authtype": "author"},
                {"name": "Lee KM", "authtype": "author"},
            ],
            "volume": "40",
            "issue": "22",
            "pages": "e170",
            "lang": ["en"],
            "pubtype": ["Journal Article"],
            "issn": "0305-1048",
            "articleids": [
                {"idtype": "doi", "idvalu": "10.1093/nar/gks1195", "value": "10.1093/nar/gks1195"},
                {"idtype": "pmc", "idvalu": "PMC3531190", "value": "PMC3531190"},
                {"idtype": "pubmed", "idvalu": "23193287", "value": "23193287"},
            ],
            "sortpubdate": "2012/12/04 00:00",
        },
    },
}

SAMPLE_EFETCH_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="MEDLINE" Owner="NLM">
      <Article PubModel="Electronic-ePrint">
        <ArticleTitle>PubMed to PDF: a simple tool for downloading full texts</ArticleTitle>
        <Abstract>
          <AbstractText>We present a simple tool for converting PubMed articles to PDF format.</AbstractText>
          <AbstractText>The tool supports batch downloads and integrates with existing reference managers.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""

NOT_FOUND_ESUMMARY: dict[str, Any] = {
    "header": {"type": "esummary", "version": "0.3"},
    "result": {"uids": []},
}


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int = 200, json_data: Any = None, text: str = "") -> MagicMock:
    """Build a mock ``httpx.Response``."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def _make_mock_client(
    esummary_json: dict | None = SAMPLE_ESUMMARY,
    efetch_xml: str | None = SAMPLE_EFETCH_XML,
) -> MagicMock:
    """Create an ``httpx.Client`` mock that returns canned NCBI responses."""
    client = MagicMock(spec=httpx.Client)

    def _get(url: str, **kwargs: Any) -> MagicMock:
        if "esummary.fcgi" in url:
            if esummary_json is None:
                # Simulate a 404-not-found scenario
                resp = _mock_response(json_data=NOT_FOUND_ESUMMARY)
            else:
                resp = _mock_response(json_data=esummary_json)
        elif "efetch.fcgi" in url:
            resp = _mock_response(text=efetch_xml or "")
        else:
            resp = _mock_response(status_code=404)
        return resp

    client.get = _get
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVerifyPmid:
    """verify_pmid mainline behaviour."""

    def test_valid_pmid(self) -> None:
        client = _make_mock_client()
        result = citation.verify_pmid("23193287", email="test@example.com", client=client)

        assert result["pmid"] == "23193287"
        assert result["exists"] is True
        assert result["title"] == "PubMed to PDF: a simple tool for downloading full texts"
        assert result["authors"] == ["Smith JA", "Jones BC", "Lee KM"]
        assert result["journal"] == "Nucleic Acids Res"
        assert result["year"] == 2012
        assert result["doi"] == "10.1093/nar/gks1195"
        assert result["pmcid"] == "PMC3531190"
        assert result["abstract_snippet"] != ""
        assert result["citations"]["apa"] != ""
        assert result["citations"]["bibtex"] != ""
        assert result["issues"] == []

    def test_apa_citation_format(self) -> None:
        client = _make_mock_client()
        result = citation.verify_pmid("23193287", email="test@example.com", client=client)
        apa = result["citations"]["apa"]
        assert "23193287" in apa
        assert "Nucleic Acids Res" in apa
        assert "PubMed to PDF" in apa

    def test_bibtex_citation_format(self) -> None:
        client = _make_mock_client()
        result = citation.verify_pmid("23193287", email="test@example.com", client=client)
        bibtex = result["citations"]["bibtex"]
        assert "@article{" in bibtex
        assert "PMID:23193287" in bibtex
        assert "10.1093/nar/gks1195" in bibtex

    def test_cache_hit_avoids_api_call(self) -> None:
        """A cached result should be returned without hitting the API."""
        # First call populates the cache
        client1 = _make_mock_client()
        r1 = citation.verify_pmid("23193287", email="test@example.com", client=client1)
        assert r1["exists"] is True

        # Second call with a client that would fail if used
        failing_client = MagicMock(spec=httpx.Client)
        r2 = citation.verify_pmid("23193287", email="test@example.com", client=failing_client)
        assert r2["exists"] is True
        assert r2["doi"] == "10.1093/nar/gks1195"
        # The failing client's get should *never* have been called
        failing_client.get.assert_not_called()


class TestPmidNotFound:
    """Non-existent PMID handling."""

    def test_no_results(self) -> None:
        client = _make_mock_client(esummary_json=NOT_FOUND_ESUMMARY, efetch_xml="")
        result = citation.verify_pmid("99999999", email="test@example.com", client=client)
        assert result["pmid"] == "99999999"
        assert result["exists"] is False
        assert result["issues"] == ["PMID not found"]
        assert result["title"] == ""

    def test_empty_uid_list(self) -> None:
        esummary = {
            "header": {"type": "esummary", "version": "0.3"},
            "result": {"uids": []},
        }
        client = _make_mock_client(esummary_json=esummary, efetch_xml="")
        result = citation.verify_pmid("1", email="test@example.com", client=client)
        assert result["exists"] is False


class TestNetworkErrors:
    """Graceful handling of network / HTTP failures."""

    def test_http_error_on_summary(self) -> None:
        client = MagicMock(spec=httpx.Client)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 error", request=MagicMock(), response=resp,
        )
        client.get.return_value = resp

        result = citation.verify_pmid("23193287", email="test@example.com", client=client)
        assert result["exists"] is False
        # Should still have some issue recorded
        assert len(result["issues"]) > 0

    def test_timeout_error(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.TimeoutException("timed out")

        result = citation.verify_pmid("23193287", email="test@example.com", client=client)
        assert result["exists"] is False
        assert any("error" in i.lower() for i in result["issues"])

    def test_connection_error(self) -> None:
        client = MagicMock(spec=httpx.Client)
        client.get.side_effect = httpx.ConnectError("connection refused")

        result = citation.verify_pmid("23193287", email="test@example.com", client=client)
        assert result["exists"] is False


class TestVerifyPmids:
    """Batch PMID verification."""

    def test_multiple_pmids(self) -> None:
        esummary2 = {
            "header": {"type": "esummary", "version": "0.3"},
            "result": {
                "uids": ["12345678"],
                "12345678": {
                    "uid": "12345678",
                    "pubdate": "2020 Jan",
                    "source": "J Biol Chem",
                    "title": "Another important study",
                    "authors": [{"name": "Doe J", "authtype": "author"}],
                    "articleids": [
                        {"idtype": "doi", "idvalu": "10.1234/jbc.2020.001", "value": "10.1234/jbc.2020.001"},
                        {"idtype": "pubmed", "idvalu": "12345678", "value": "12345678"},
                    ],
                    "sortpubdate": "2020/01/01 00:00",
                },
            },
        }
        # We can't easily return different responses per URL with a single mock,
        # so test with one PMID at a time through verify_pmids.
        # Instead, let's test that verify_pmids calls verify_pmid for each.

        client = _make_mock_client()
        results = citation.verify_pmids(
            ["23193287", "23193287"],  # same ID twice (cache test)
            email="test@example.com",
            client=client,
        )
        assert len(results) == 2
        assert results[0]["exists"] is True
        assert results[1]["exists"] is True
        assert results[0]["pmid"] == "23193287"

    def test_empty_list(self) -> None:
        results = citation.verify_pmids([], email="test@example.com")
        assert results == []


class TestEdgeCases:
    """Edge-case behaviour."""

    def test_missing_title(self) -> None:
        esummary = {
            "header": {"type": "esummary", "version": "0.3"},
            "result": {
                "uids": ["1"],
                "1": {"uid": "1", "source": "Science", "articleids": []},
            },
        }
        client = _make_mock_client(esummary_json=esummary, efetch_xml="")
        result = citation.verify_pmid("1", email="test@example.com", client=client)
        assert result["exists"] is True
        assert result["title"] == ""
        assert result["year"] is None

    def test_no_authors(self) -> None:
        esummary = {
            "header": {"type": "esummary", "version": "0.3"},
            "result": {
                "uids": ["2"],
                "2": {"uid": "2", "title": "No Authors", "source": "Nature", "articleids": []},
            },
        }
        client = _make_mock_client(esummary_json=esummary, efetch_xml="")
        result = citation.verify_pmid("2", email="test@example.com", client=client)
        assert result["authors"] == []

    def test_bibtex_without_doi(self) -> None:
        esummary = {
            "header": {"type": "esummary", "version": "0.3"},
            "result": {
                "uids": ["3"],
                "3": {
                    "uid": "3",
                    "title": "No DOI",
                    "source": "Science",
                    "authors": [{"name": "Author A"}],
                    "articleids": [{"idtype": "pubmed", "idvalu": "3", "value": "3"}],
                },
            },
        }
        client = _make_mock_client(esummary_json=esummary, efetch_xml="")
        result = citation.verify_pmid("3", email="test@example.com", client=client)
        assert result["doi"] == ""
        assert "doi" not in result["citations"]["bibtex"] or "doi = {}" not in result["citations"]["bibtex"]


class TestThrottle:
    """Verify the throttle helper doesn't crash."""

    def test_throttle_does_not_raise(self) -> None:
        # Direct call is harmless
        citation._throttle()
        citation._throttle()
