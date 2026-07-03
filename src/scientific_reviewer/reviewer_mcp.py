"""
Scientific Reviewer — MCP Server

Exposes scientific review capabilities as MCP (Model Context Protocol) tools.
Compatible with Claude Desktop, Claude Code, Hermes Agent, and any MCP client.

Usage:
    scientific-reviewer mcp              # Start MCP server (stdio mode)
    scientific-reviewer mcp --port 8910  # Start in HTTP+SSE mode
"""
import sys
from typing import Any

from . import orchestrator
from .cache import clear as cache_clear, status as cache_status
from .citation import verify_pmid, verify_pmids
from .gene import verify_genes
from .math import verify_math


def create_server():
    """Create and configure the MCP server.

    Returns:
        FastMCP server instance (call .run() to start).
    """
    try:
        from fastmcp import FastMCP
    except ImportError:
        print("Error: fastmcp not installed. pip install 'scientific-reviewer[mcp]'")
        sys.exit(1)

    server = FastMCP("Scientific Reviewer", version="0.1.0")

    # ─── Tool: review_text ─────────────────────────────────
    @server.tool()
    def review_text(text: str) -> dict[str, Any]:
        """Run full scientific review on a piece of text.

        Verifies citations (PMIDs), gene symbols, statistical claims,
        and GEO accessions. Returns a structured report with issues.

        Args:
            text: The scientific text to review.

        Returns:
            Report with verified claims, issues, and confidence score.
        """
        return orchestrator.review_text(text)

    # ─── Tool: verify_citation ─────────────────────────────
    @server.tool()
    def verify_citation(pmid: str) -> dict[str, Any]:
        """Verify a single PMID against PubMed.

        Args:
            pmid: PubMed ID (e.g., "23193287").

        Returns:
            Structured verification with title, authors, journal, etc.
        """
        return verify_pmid(pmid)

    # ─── Tool: verify_citations ────────────────────────────
    @server.tool()
    def verify_citations(pmids: list[str]) -> list[dict[str, Any]]:
        """Verify multiple PMIDs against PubMed.

        Args:
            pmids: List of PubMed IDs (e.g., ["23193287", "28723893"]).

        Returns:
            List of structured verification results.
        """
        return verify_pmids(pmids)

    # ─── Tool: verify_gene ─────────────────────────────────
    @server.tool()
    def verify_gene(symbol: str) -> dict[str, Any]:
        """Verify a single gene symbol against UniProt and Ensembl.

        Args:
            symbol: Gene symbol (e.g., "TP53", "BRCA1").

        Returns:
            Verification with UniProt accession, protein name, location.
        """
        results = verify_genes([symbol])
        return results[0] if results else {"symbol": symbol, "valid": False, "issues": ["No result"]}

    # ─── Tool: verify_genes ────────────────────────────────
    @server.tool()
    def verify_genes_batch(symbols: list[str]) -> list[dict[str, Any]]:
        """Verify multiple gene symbols.

        Args:
            symbols: List of gene symbols (e.g., ["TP53", "BRCA1"]).

        Returns:
            List of verification results.
        """
        return verify_genes(symbols)

    # ─── Tool: verify_math ─────────────────────────────────
    @server.tool()
    def verify_math_text(text: str) -> dict[str, Any]:
        """Verify LaTeX math expressions and statistical claims.

        Checks p-values, fold-changes, confidence intervals, percentages,
        and LaTeX syntax. Flags impossible values and suspicious patterns.

        Args:
            text: Text containing math expressions and/or statistics.

        Returns:
            Report with verified and flagged items.
        """
        return verify_math(text)

    # ─── Tool: cache_status ────────────────────────────────
    @server.tool()
    def review_cache_status() -> dict[str, Any]:
        """Get review cache status (entry count, session start)."""
        return cache_status()

    # ─── Tool: cache_clear ─────────────────────────────────
    @server.tool()
    def review_cache_clear() -> dict[str, str]:
        """Clear the review cache."""
        cache_clear()
        return {"status": "cleared"}

    return server


def run_server(host: str = "127.0.0.1", port: int = 8910):
    """Start the MCP server.

    In stdio mode (default), communicates over stdin/stdout for
    integration with Claude Code, Hermes Agent, etc.

    With --port, starts in HTTP+SSE mode for remote access.

    Args:
        host: Server host (ignored in stdio mode).
        port: Server port (ignored in stdio mode).
    """
    server = create_server()

    if port:
        print(f"Starting Scientific Reviewer MCP server on http://{host}:{port}", file=sys.stderr)
        print("Connect your MCP client to this endpoint.", file=sys.stderr)
        server.run(host=host, port=port)
    else:
        # stdio mode — default for MCP
        server.run()


if __name__ == "__main__":
    run_server()
