"""Math verification module for scientific-reviewer.

Provides functions to extract and verify mathematical expressions and
statistical claims from scientific text.  The top-level :func:`verify_math`
function runs the full pipeline and returns a structured report.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# LaTeX display math — $$...$$  (must be matched first)
_RE_DISPLAY_MATH = re.compile(r'\$\$(.*?)\$\$', re.DOTALL)

# LaTeX inline math — $...$
# Negative lookahead/lookbehind so $$ is not mistaken for $.
# The captured expression must contain at least one letter, backslash,
# underscore, caret, or brace — prices like ``$5.00`` are ignored.
_RE_INLINE_MATH = re.compile(
    r'(?<!\$)\$(?!\$)((?:[^$]*?[a-zA-Z\\{}_^]|[a-zA-Z\\{}_^][^$]*?))(?<!\$)\$(?!\$)',  # noqa: E501
    re.DOTALL,
)

# P-values
#   p = 0.03   p<0.001   p-value = 0.05   P = 0.01   p = -0.5
_RE_PVALUE = re.compile(
    r'(?:p|P)(?:\s*-\s*|\s+)?(?:value\s*)?\s*([<>=])\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)'
)

# Fold change  (positive values only)
#   fold change = 2.5   FC = 1.2   fold-change = 3.0
_RE_FOLD_CHANGE = re.compile(
    r'(?:fold[\s-]?change|FC)\s*[=:]\s*(\d+\.?\d*(?:[eE][+-]?\d+)?)',
    re.IGNORECASE,
)

# log2 fold change  (may be negative)
#   log2FC = -2.5   log2 FC = 1.5   log2 fold change = -1.2
_RE_LOG2FC = re.compile(
    r'log2[\s_]*(?:FC|fold[\s-]?change)?\s*[=:]\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)',
    re.IGNORECASE,
)

# Percentage  45%  95.2%  0.5%
_RE_PERCENTAGE = re.compile(r'(\d+\.?\d*)\s*%')

# Confidence interval — bracket form  [lower, upper]
_RE_CI_BRACKET = re.compile(r'\[(\d+\.?\d*)\s*,\s*(\d+\.?\d*)\]')

# Confidence interval — paren range form  (lower–upper)
_RE_CI_PAREN = re.compile(r'\((\d+\.?\d*)\s*[–-]\s*(\d+\.?\d*)\)')

# Sample size  n = 30   N=100
_RE_SAMPLE_SIZE = re.compile(r'[nN]\s*[=:]\s*(\d+)')

# ---------------------------------------------------------------------------
# Sympy import (best-effort)
# ---------------------------------------------------------------------------

_SYMPY_AVAILABLE = False
_SYMPY_PARSE = None

try:
    import sympy  # # noqa: F401
    from sympy.parsing.latex import parse_latex as _sympy_parse_latex

    _SYMPY_PARSE = _sympy_parse_latex
    # Verify antlr4 backend is actually available
    _SYMPY_PARSE("x")
    _SYMPY_AVAILABLE = True
except Exception:
    # sympy installed but antlr4-python3-runtime missing — degrade gracefully
    _SYMPY_AVAILABLE = False
    _SYMPY_PARSE = None


# ---------------------------------------------------------------------------
# Math extraction
# ---------------------------------------------------------------------------


def extract_math(text: str) -> list[dict[str, Any]]:
    """Extract LaTeX math expressions from *text*.

    Both display math (``$$...$$``) and inline math (``$...$``) are
    extracted.  Inline expressions that look like prices (e.g. ``$5.00``)
    are excluded.  Each returned dict contains:

    * ``type`` — ``"inline"`` or ``"display"``
    * ``latex`` — the raw expression **without** delimiters
    * ``pos`` — character offset in the original *text*

    Parameters
    ----------
    text : str
        Scientific text that may contain LaTeX math.

    Returns
    -------
    list[dict[str, Any]]
        Extracted math expressions.
    """
    expressions: list[dict[str, Any]] = []

    # 1. Display math $$...$$
    for m in _RE_DISPLAY_MATH.finditer(text):
        expressions.append(
            {
                "type": "display",
                "latex": m.group(1).strip(),
                "pos": m.start(),
            }
        )

    # 2. Mask display-math regions so inline regex doesn't clash
    cleaned = _RE_DISPLAY_MATH.sub(lambda m: " " * len(m.group(0)), text)

    # 3. Inline math $...$
    for m in _RE_INLINE_MATH.finditer(cleaned):
        expressions.append(
            {
                "type": "inline",
                "latex": m.group(1).strip(),
                "pos": m.start(),
            }
        )

    expressions.sort(key=lambda x: x["pos"])
    return expressions


# ---------------------------------------------------------------------------
# Statistical claim extraction
# ---------------------------------------------------------------------------


def extract_stats(text: str) -> list[dict[str, Any]]:
    """Extract statistical claims from *text*.

    Recognised claim types:

    * ``"p-value"`` — e.g. ``p = 0.03``, ``p < 0.001``
    * ``"fold-change"`` — e.g. ``fold change = 2.5``, ``FC = 1.2``
    * ``"log2FC"`` — e.g. ``log2FC = -2.5``
    * ``"percentage"`` — e.g. ``45%``, ``95.2%``
    * ``"confidence-interval"`` — e.g. ``[1.2, 4.8]``, ``(0.5 – 1.3)``
    * ``"sample-size"`` — e.g. ``n = 30``, ``N = 100``

    Each returned dict contains at least ``raw`` (the matched string),
    ``type`` (the claim type), and type-specific parsed values.

    Parameters
    ----------
    text : str
        Scientific text.

    Returns
    -------
    list[dict[str, Any]]
        Extracted statistical claims.
    """
    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    def _add_claim(d: dict[str, Any]) -> None:
        """Prevent duplicate claims based on raw text + start position."""
        key = (d["raw"], d.get("pos", 0))
        if key not in seen:
            seen.add(key)
            claims.append(d)

    # ---- p-values ----
    for m in _RE_PVALUE.finditer(text):
        _add_claim(
            {
                "raw": m.group(0).strip(),
                "type": "p-value",
                "value": float(m.group(2)),
                "comparison": m.group(1),
                "pos": m.start(),
            }
        )

    # ---- fold changes ----
    for m in _RE_FOLD_CHANGE.finditer(text):
        _add_claim(
            {
                "raw": m.group(0).strip(),
                "type": "fold-change",
                "value": float(m.group(1)),
                "pos": m.start(),
            }
        )

    # ---- log2 fold changes ----
    for m in _RE_LOG2FC.finditer(text):
        _add_claim(
            {
                "raw": m.group(0).strip(),
                "type": "log2FC",
                "value": float(m.group(1)),
                "pos": m.start(),
            }
        )

    # ---- percentages ----
    for m in _RE_PERCENTAGE.finditer(text):
        _add_claim(
            {
                "raw": m.group(0).strip(),
                "type": "percentage",
                "value": float(m.group(1)),
                "pos": m.start(),
            }
        )

    # ---- confidence intervals (bracket) ----
    for m in _RE_CI_BRACKET.finditer(text):
        _add_claim(
            {
                "raw": m.group(0).strip(),
                "type": "confidence-interval",
                "lower": float(m.group(1)),
                "upper": float(m.group(2)),
                "pos": m.start(),
            }
        )

    # ---- confidence intervals (paren range) ----
    for m in _RE_CI_PAREN.finditer(text):
        _add_claim(
            {
                "raw": m.group(0).strip(),
                "type": "confidence-interval",
                "lower": float(m.group(1)),
                "upper": float(m.group(2)),
                "pos": m.start(),
            }
        )

    # ---- sample sizes ----
    for m in _RE_SAMPLE_SIZE.finditer(text):
        _add_claim(
            {
                "raw": m.group(0).strip(),
                "type": "sample-size",
                "value": int(m.group(1)),
                "pos": m.start(),
            }
        )

    claims.sort(key=lambda x: x.get("pos", 0))
    return claims


# ---------------------------------------------------------------------------
# Individual verifiers
# ---------------------------------------------------------------------------


def verify_latex_syntax(latex: str) -> list[str]:
    """Check basic LaTeX syntax in an expression.

    Verifications performed:

    * Expression is not empty.
    * No unmatched curly braces ``{`` / ``}``.
    * No ``\\begin`` without ``\\end``.
    * Expression can be parsed by **sympy** (best-effort; skipped when
      sympy is not installed).

    Parameters
    ----------
    latex : str
        A LaTeX math expression (with or without delimiters).

    Returns
    -------
    list[str]
        Human-readable issue descriptions (empty when the expression is OK).
    """
    issues: list[str] = []

    if not latex.strip():
        issues.append("LaTeX SYNTAX: empty expression")
        return issues

    # brace balance
    depth = 0
    for i, ch in enumerate(latex):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                issues.append(
                    f"LaTeX SYNTAX: unmatched '}}' at position {i}"
                )
                break
    if depth > 0:
        issues.append(f"LaTeX SYNTAX: {depth} unclosed brace(s)")

    # unmatched \begin / \end
    if "\\begin" in latex and "\\end" not in latex:
        issues.append("LaTeX SYNTAX: \\begin without \\end")

    # sympy best-effort parse
    if _SYMPY_PARSE is not None:
        try:
            _SYMPY_PARSE(latex)
        except Exception as exc:
            issues.append(f"LaTeX parse error: {exc}")

    return issues


def verify_pvalue(pval: dict[str, Any]) -> list[str]:
    """Verify a p-value claim.

    Checks that the numeric value is in the interval :math:`[0, 1]`.

    Parameters
    ----------
    pval : dict
        A p-value claim dict as produced by :func:`extract_stats`.

    Returns
    -------
    list[str]
        Issue descriptions (empty when the claim is plausible).
    """
    issues: list[str] = []
    value = pval.get("value")
    comparison = pval.get("comparison", "=")

    if value is not None:
        if value < 0.0:
            issues.append(
                f"IMPOSSIBLE: p {comparison} {value} — "
                "p-value cannot be negative"
            )
        elif value > 1.0 and comparison == "=":
            issues.append(
                f"IMPOSSIBLE: p {comparison} {value} — "
                "p-value cannot exceed 1"
            )
        elif value > 1.0:
            issues.append(
                f"SUSPICIOUS: p {comparison} {value} — "
                "p-values are typically ≤ 1"
            )

    return issues


def verify_fold_change(fc: dict[str, Any]) -> list[str]:
    """Verify a fold-change claim.

    Fold change must be positive (a negative fold-change is physically
    meaningless; down-regulation is expressed via *log2* fold change).

    Parameters
    ----------
    fc : dict
        A fold-change claim dict as produced by :func:`extract_stats`.

    Returns
    -------
    list[str]
        Issue descriptions (empty when the claim is plausible).
    """
    issues: list[str] = []
    value = fc.get("value")
    if value is not None and value <= 0:
        issues.append(
            f"SUSPICIOUS: fold-change = {value} — "
            "should be positive (use log2FC for down-regulation)"
        )
    return issues


def verify_percentage(pct: dict[str, Any]) -> list[str]:
    """Verify a percentage claim.

    Checks that the value is in the range :math:`[0, 100]`.

    Parameters
    ----------
    pct : dict
        A percentage claim dict as produced by :func:`extract_stats`.

    Returns
    -------
    list[str]
        Issue descriptions (empty when the claim is plausible).
    """
    issues: list[str] = []
    value = pct.get("value")
    if value is not None:
        if value < 0.0:
            issues.append(
                f"IMPOSSIBLE: {value}% — percentage cannot be negative"
            )
        elif value > 100.0:
            issues.append(
                f"IMPOSSIBLE: {value}% — cannot exceed 100%"
            )
    return issues


def verify_confidence_interval(ci: dict[str, Any]) -> list[str]:
    """Verify a confidence-interval claim.

    Checks:

    * Lower bound ≤ upper bound.
    * Interval is not zero-width (identical bounds).

    Parameters
    ----------
    ci : dict
        A confidence-interval claim dict as produced by :func:`extract_stats`.

    Returns
    -------
    list[str]
        Issue descriptions (empty when the claim is plausible).
    """
    issues: list[str] = []
    lower = ci.get("lower")
    upper = ci.get("upper")

    if lower is not None and upper is not None:
        if lower > upper:
            issues.append(
                f"INVALID: CI [{lower}, {upper}] — "
                "lower bound > upper bound"
            )
        if lower == upper:
            issues.append(
                f"SUSPICIOUS: CI [{lower}, {upper}] — zero-width interval"
            )

    return issues


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def verify_math(text: str) -> dict[str, Any]:
    """Run the full math verification pipeline on *text*.

    The pipeline:

    1. Extracts all LaTeX math expressions and statistical claims.
    2. Verifies each extracted item with the appropriate checker.
    3. Aggregates results into a structured report.

    Parameters
    ----------
    text : str
        Scientific text to analyse.

    Returns
    -------
    dict[str, Any]
        Report with the following keys:

        * **timestamp** (*str*) — ISO-8601 UTC timestamp.
        * **text_length** (*int*) — character count of input.
        * **math_expressions** (*list*) — each entry has ``type``,
          ``latex`` and ``issues``.
        * **statistical_claims** (*list*) — each entry has ``raw``,
          ``type`` and ``issues``.
        * **issues** (*list[str]*) — global-level issues (currently empty
          placeholder).
        * **verified** (*int*) — count of items with zero issues.
        * **flagged** (*int*) — count of items with at least one issue.
    """
    ts = datetime.now(timezone.utc).isoformat()

    math_exprs = extract_math(text)
    stats = extract_stats(text)

    # Verify each math expression
    verified_math: list[dict[str, Any]] = []
    for expr in math_exprs:
        issues = verify_latex_syntax(expr["latex"])
        verified_math.append(
            {
                "type": expr["type"],
                "latex": expr["latex"],
                "issues": issues,
            }
        )

    # Verify each statistical claim
    verified_stats: list[dict[str, Any]] = []
    for claim in stats:
        t = claim["type"]
        if t == "p-value":
            issues = verify_pvalue(claim)
        elif t == "fold-change":
            issues = verify_fold_change(claim)
        elif t == "percentage":
            issues = verify_percentage(claim)
        elif t == "confidence-interval":
            issues = verify_confidence_interval(claim)
        else:
            # log2FC, sample-size: no dedicated verification
            issues = []

        verified_stats.append(
            {
                "raw": claim["raw"],
                "type": t,
                "issues": issues,
            }
        )

    # Count verified vs flagged
    all_issue_lists: list[list[str]] = [
        e["issues"] for e in verified_math
    ] + [s["issues"] for s in verified_stats]

    verified_count = sum(1 for iss in all_issue_lists if not iss)
    flagged_count = sum(1 for iss in all_issue_lists if iss)

    return {
        "timestamp": ts,
        "text_length": len(text),
        "math_expressions": verified_math,
        "statistical_claims": verified_stats,
        "issues": [],
        "verified": verified_count,
        "flagged": flagged_count,
    }
