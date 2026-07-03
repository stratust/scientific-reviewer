#!/usr/bin/env python3
"""Example: Connect to the Scientific Reviewer MCP server and run a review."""
import json
import subprocess
import sys


def test_stdio_mcp():
    """Test the MCP server via stdio."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "scientific_reviewer.reviewer_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Send a JSON-RPC request to call review_text
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "review_text",
            "arguments": {
                "text": "TP53 regulates CD4 expression (p < 0.001). PMID 23193287."
            }
        }
    })

    stdout, stderr = proc.communicate(input=request + "\n", timeout=10)
    proc.terminate()

    try:
        result = json.loads(stdout)
        issues = result.get("result", {}).get("content", [{}])[0].get("text", "")
        data = json.loads(issues) if isinstance(issues, str) else issues
        print(f"✅ PMIDs verified: {len(data.get('pmids', []))}")
        print(f"✅ Genes verified: {len(data.get('genes', []))}")
        print(f"⚠️  Issues: {len(data.get('issues', []))}")
        for iss in data.get('issues', []):
            print(f"   - {iss}")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error: {e}")
        print(f"stdout: {stdout[:500]}")
        print(f"stderr: {stderr[:500]}")


if __name__ == "__main__":
    test_stdio_mcp()
