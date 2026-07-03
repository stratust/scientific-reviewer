# 🔬 Scientific Reviewer

[![CI](https://github.com/stratust/scientific-reviewer/actions/workflows/ci.yml/badge.svg)](https://github.com/stratust/scientific-reviewer/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**AI-powered research verification toolkit** — citation checking, gene validation, math verification, and more. Exposes a CLI, Python API, and **MCP server** for integration with AI agents (Claude Code, Hermes Agent, Cursor, etc.).

Inspired by Anthropic's [Claude Science](https://www.anthropic.com/news/claude-science-ai-workbench), built to be model-agnostic, local-first, and freely extensible.

---

## Features

| Module | What it checks | Data source |
|---|---|---|
| **Citation** | PMID/DOI existence, title, authors, journal, year, APA/BibTeX | NCBI E-utilities (PubMed) |
| **Gene** | Gene symbol validity, UniProt accession, protein name, genomic location, GO terms | UniProt + Ensembl |
| **Math** | LaTeX syntax, p-values, fold-change, confidence intervals, percentages | Regex + sympy |
| **Orchestrator** | Full pipeline: classifies claims → dispatches specialists → merges results | All of the above |

## Quickstart

```bash
# Install
pip install scientific-reviewer

# Or install with MCP support
pip install "scientific-reviewer[mcp]"

# Or from source
git clone https://github.com/stratust/scientific-reviewer.git
cd scientific-reviewer
pip install -e ".[mcp,dev]"
```

## CLI Usage

```bash
# Full review
scientific-reviewer review "TP53 regulates CD4 expression (p < 0.001). PMID 23193287."
scientific-reviewer review --file paper.md

# Citation verification
scientific-reviewer citations --pmids 23193287,28723893

# Gene verification
scientific-reviewer genes --symbols TP53,BRCA1,CD4

# Math/LaTeX verification
scientific-reviewer math --text "p = 0.03, 95% CI [1.2, 4.8]"
scientific-reviewer math --file paper.tex

# Cache management
scientific-reviewer cache status
scientific-reviewer cache clear

# Start MCP server
scientific-reviewer mcp
```

## Python API

```python
from scientific_reviewer import orchestrator
from scientific_reviewer.citation import verify_pmid, verify_pmids
from scientific_reviewer.gene import verify_genes, extract_gene_symbols
from scientific_reviewer.math import verify_math

# Full review
report = orchestrator.review_text("TP53 regulates CD4 (p<0.01). PMID 23193287.")
print(report["issues"])

# Verify a PMID
result = verify_pmid("23193287")
print(result["title"])  # "GenBank."

# Verify genes
results = verify_genes(["TP53", "BRCA1"])
for r in results:
    print(f"{r['symbol']}: {r['uniprot_accession']} (valid={r['valid']})")

# Verify math
math_report = verify_math("p = 0.03, 95% CI [1.2, 4.8]")
print(f"{math_report['verified']} verified, {math_report['flagged']} flagged")
```

## MCP Server

The MCP server allows AI agents (Claude Code, Hermes Agent, Cursor) to call review tools directly.

### Starting the server

```bash
# stdio mode (for Claude Code, Hermes Agent)
scientific-reviewer mcp

# HTTP+SSE mode (for remote access)
scientific-reviewer mcp --port 8910
```

### Registering with Hermes Agent

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  scientific-reviewer:
    command: scientific-reviewer
    args: [mcp]
```

### Registering with Claude Code

```bash
claude mcp add scientific-reviewer -- python -m scientific_reviewer.reviewer_mcp
```

### Available MCP tools

| Tool | Description |
|---|---|
| `review_text(text)` | Full scientific review pipeline |
| `verify_citation(pmid)` | Verify a single PMID |
| `verify_citations(pmids)` | Verify multiple PMIDs |
| `verify_gene(symbol)` | Verify a single gene |
| `verify_genes_batch(symbols)` | Verify multiple genes |
| `verify_math_text(text)` | Verify LaTeX and statistics |
| `review_cache_status()` | Cache usage stats |
| `review_cache_clear()` | Clear review cache |

## Comparison: Scientific Reviewer vs Claude Science

| Feature | **Scientific Reviewer** | Claude Science |
|---|---|---|
| Citation verification | ✅ Free (NCBI APIs) | ✅ |
| Gene validation (UniProt + Ensembl) | ✅ Free | ✅ |
| Math/statistics verification | ✅ | ✅ |
| **MCP server** | **✅ Open standard** | ⚠️ Proprietary |
| **Model-agnostic** | **✅ Any LLM** | 🔒 Claude only |
| **Local-first** | **✅ Runs anywhere** | ⚠️ Sends data to Anthropic |
| **Cache persistence** | **✅** | ❌ |
| **Open source** | **✅ MIT** | ❌ |
| **Python API** | **✅** | ❌ (app-only) |
| **CLI** | **✅** | ❌ |
| **Actor-critic writing** | ✅ | ✅ |
| **Figure provenance** | ✅ | ✅ |
| **Background pipeline watcher** | ✅ | ❌ |
| **Git integration** | ✅ | ❌ |
| 3D protein viewer | ❌ (use ChimeraX) | ✅ |
| HPC/Slurm orchestration | ❌ | ✅ |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI (argparse)                       │
│                    scientific-reviewer <cmd>                  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                    ┌───────┴───────┐
                    │  MCP Server   │  ← AI agents connect here
                    │  (FastMCP)    │
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
       ┌──────────┐  ┌──────────┐  ┌──────────┐
       │ Citation │  │   Gene   │  │   Math   │
       │  Module  │  │  Module  │  │  Module  │
       └──────────┘  └──────────┘  └──────────┘
              │             │             │
              └─────────────┼─────────────┘
                            ▼
              ┌─────────────────────────┐
              │      Orchestrator       │
              └─────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │         Cache           │
              │  (~/.scientific_reviewer)│
              └─────────────────────────┘
```

## Project Structure

```
scientific-reviewer/
├── pyproject.toml          # Package config + dependencies
├── README.md               # This file
├── LICENSE                 # MIT
├── .github/workflows/ci.yml
└── src/scientific_reviewer/
    ├── __init__.py          # Version
    ├── __main__.py          # python -m support
    ├── cli.py               # Command-line interface
    ├── cache.py             # Persistent JSON cache
    ├── citation.py          # PMID/DOI verification
    ├── gene.py              # Gene symbol verification
    ├── math.py              # LaTeX/math verification
    ├── orchestrator.py      # Multi-agent coordinator
    └── reviewer_mcp.py      # MCP server (FastMCP)
```

## Development

```bash
# Install dev dependencies
pip install -e ".[mcp,dev]"

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=scientific_reviewer

# Lint
ruff check src/ tests/

# Type check
pyright src/
```

## License

MIT License — see [LICENSE](LICENSE).

## Acknowledgements

Inspired by Anthropic's Claude Science and built for the Hermes Agent ecosystem.
