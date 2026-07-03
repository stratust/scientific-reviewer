"""
Scientific Reviewer — CLI Entry Point

Usage:
    scientific-reviewer review "TP53 regulates CD4 (p<0.01). PMID 23193287."
    scientific-reviewer review --file README.md
    scientific-reviewer citations --pmids 23193287,28723893
    scientific-reviewer genes --symbols TP53,BRCA1,CD4
    scientific-reviewer math --text "p = 0.03, 95% CI [1.2, 4.8]"
    scientific-reviewer cache status
    scientific-reviewer cache clear
    scientific-reviewer mcp
"""
import argparse
import json
import sys
import textwrap


def print_json(data):
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=2, default=str))


def cmd_review(args):
    """Run full review pipeline."""
    from .orchestrator import review_text

    if args.file:
        with open(args.file) as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    report = review_text(text)
    format_report(report)


def format_report(report):
    """Format review report for terminal display."""
    lines = []
    lines.append("═" * 63)
    lines.append("🔬 SCIENTIFIC REVIEWER REPORT")
    lines.append(f"   {report['timestamp']}")
    lines.append(f"   Text: {report['text_length']} chars")
    lines.append("═" * 63)

    cf = report["claims_found"]
    found = [f"{k}={v}" for k, v in cf.items() if v > 0]
    lines.append(f"\n📊 Claims found: {' | '.join(found) if found else 'None'}")

    if not found:
        lines.append("\n✅ No verifiable claims found.")
        print("\n".join(lines))
        return

    if report["pmids"]:
        lines.append(f"\n📝 CITATIONS ({len(report['pmids'])} checked)")
        for c in report["pmids"]:
            status = "✅" if c.get("exists") else "❌"
            lines.append(f"  {status} PMID {c.get('pmid', '?')}")
            if c.get("exists"):
                title = (c.get('title') or '')[:80]
                lines.append(f"     {title}")
                lines.append(f"     {c.get('journal', '')} ({c.get('year', '')})")
            for iss in c.get("issues", []):
                lines.append(f"     ⚠️  {iss}")

    if report["genes"]:
        lines.append(f"\n🧬 GENES ({len(report['genes'])} checked)")
        for g in report["genes"]:
            status = "✅" if g.get("valid") else "❌"
            lines.append(f"  {status} {g.get('symbol', '')}")
            if g.get("valid") and g.get("uniprot_accession"):
                lines.append(f"     {g['uniprot_accession']} — {(g.get('uniprot_name') or '')[:70]}")
            if not g.get("valid") and g.get("suggestions"):
                lines.append(f"     💡 Suggestions: {', '.join(g['suggestions'][:4])}")

    if report["issues"]:
        lines.append(f"\n❌ ISSUES ({len(report['issues'])} found)")
        for iss in report["issues"]:
            lines.append(f"  ⚠️  {iss}")

    s = report.get("stats", {})
    lines.append(f"\n{'─' * 63}")
    lines.append(f"📈 Summary: {s.get('total_verified', 0)} verified | {s.get('total_issues', 0)} issues")
    if s.get('total_issues', 0) > 0:
        lines.append(f"⚠️  Confidence: {report.get('confidence', 'unknown').upper()}")
    else:
        lines.append("✅ ALL CLEAN — no issues found")
    lines.append("═" * 63)

    print("\n".join(lines))


def cmd_citations(args):
    """Verify PMIDs."""
    from .citation import verify_pmids

    pmids = [p.strip() for p in args.pmids.split(",") if p.strip()]
    if not pmids:
        print("Error: provide at least one PMID")
        sys.exit(1)
    results = verify_pmids(pmids)
    print_json(results if len(results) > 1 else results[0])


def cmd_genes(args):
    """Verify gene symbols."""
    from .gene import verify_genes

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("Error: provide at least one gene symbol")
        sys.exit(1)
    results = verify_genes(symbols)
    print_json(results)


def cmd_math(args):
    """Verify math/LaTeX."""
    from .math import verify_math

    text = args.text if args.text else sys.stdin.read()
    result = verify_math(text)

    if args.json:
        print_json(result)
    else:
        lines = ["📐 MATH VERIFICATION"]
        lines.append("═" * 63)

        if result["math_expressions"]:
            lines.append(f"\n📝 LaTeX ({len(result['math_expressions'])})")
            for expr in result["math_expressions"]:
                icon = "⚠️" if expr.get("issues") else "✅"
                latex_preview = (expr.get("latex") or "")[:70]
                lines.append(f"  {icon} ${latex_preview}...$")
                for iss in expr.get("issues", []):
                    lines.append(f"     {iss}")

        if result["statistical_claims"]:
            lines.append(f"\n📊 Stats ({len(result['statistical_claims'])})")
            for stat in result["statistical_claims"]:
                icon = "⚠️" if stat.get("issues") else "✅"
                lines.append(f"  {icon} {stat.get('raw', '')}")
                for iss in stat.get("issues", []):
                    lines.append(f"     {iss}")

        lines.append(f"\n{'─' * 63}")
        lines.append(f"📈 {result['verified']} verified | {result['flagged']} flagged")
        if result["issues"]:
            lines.append(f"⚠️  {result['flagged']} issues found")
        else:
            lines.append("✅ ALL CLEAN")
        lines.append("═" * 63)
        print("\n".join(lines))


def cmd_cache(args):
    """Manage review cache."""
    from .cache import status as cache_status, clear as cache_clear

    if args.action == "status":
        status = cache_status()
        print_json(status)
    elif args.action == "clear":
        cache_clear()
        print('{"status": "cleared"}')


def cmd_mcp(args):
    """Start MCP server."""
    try:
        from .reviewer_mcp import run_server
        run_server(host=args.host, port=args.port)
    except ImportError as e:
        print("Error: MCP dependencies not installed. Run: pip install 'scientific-reviewer[mcp]'")
        print(f"Detail: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Scientific Reviewer — AI-powered research verification toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              scientific-reviewer review "TP53 regulates CD4 (p<0.01). PMID 23193287."
              scientific-reviewer review --file paper.md
              scientific-reviewer citations --pmids 23193287,28723893
              scientific-reviewer genes --symbols TP53,BRCA1,CD4
              scientific-reviewer math --text "p = 0.03, 95% CI [1.2, 4.8]"
              scientific-reviewer cache status
              scientific-reviewer mcp
        """),
    )
    subparsers = parser.add_subparsers(dest="command")

    # review
    rp = subparsers.add_parser("review", help="Full scientific review of text")
    rp.add_argument("text", nargs="?", help="Text to review")
    rp.add_argument("--file", "-f", help="File to review")

    # citations
    cp = subparsers.add_parser("citations", help="Verify PMIDs")
    cp.add_argument("--pmids", required=True, help="Comma-separated PMIDs")
    cp.add_argument("--json", action="store_true", help="JSON output")

    # genes
    gp = subparsers.add_parser("genes", help="Verify gene symbols")
    gp.add_argument("--symbols", required=True, help="Comma-separated gene symbols")
    gp.add_argument("--json", action="store_true", help="JSON output")

    # math
    mp = subparsers.add_parser("math", help="Verify LaTeX/math expressions")
    mp.add_argument("text", nargs="?", help="Text to verify")
    mp.add_argument("--json", action="store_true", help="JSON output")

    # cache
    cap = subparsers.add_parser("cache", help="Manage review cache")
    cap.add_argument("action", choices=["status", "clear"])

    # mcp
    mcp_p = subparsers.add_parser("mcp", help="Start MCP server")
    mcp_p.add_argument("--host", default="127.0.0.1", help="Server host")
    mcp_p.add_argument("--port", type=int, default=8910, help="Server port")

    args = parser.parse_args()

    if args.command == "review":
        cmd_review(args)
    elif args.command == "citations":
        cmd_citations(args)
    elif args.command == "genes":
        cmd_genes(args)
    elif args.command == "math":
        cmd_math(args)
    elif args.command == "cache":
        cmd_cache(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
