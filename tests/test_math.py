"""Tests for the math verification module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the src directory is on the path
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from scientific_reviewer.math import (  # noqa: E402
    extract_math,
    extract_stats,
    verify_confidence_interval,
    verify_fold_change,
    verify_latex_syntax,
    verify_math,
    verify_percentage,
    verify_pvalue,
)


# ============================================================================
# extract_math
# ============================================================================


class TestExtractMath:
    def test_inline_math(self):
        """Extract simple inline $...$ expression."""
        exprs = extract_math("The expression $x^2 + y^2 = 1$ is a circle.")
        assert len(exprs) == 1
        assert exprs[0]["type"] == "inline"
        assert "x^2 + y^2 = 1" in exprs[0]["latex"]

    def test_display_math(self):
        """Extract simple display $$...$$ expression."""
        exprs = extract_math(
            "Consider $$\\int_a^b f(x)\\,dx$$ which is the integral."
        )
        assert len(exprs) == 1
        assert exprs[0]["type"] == "display"
        assert "\\int_a^b f(x)\\,dx" in exprs[0]["latex"]

    def test_inline_and_display(self):
        """Both inline and display math extracted."""
        text = r"A sum $\sum_{i=1}^n i$ and $$\frac{n(n+1)}{2}$$."
        exprs = extract_math(text)
        assert len(exprs) == 2
        types = [e["type"] for e in exprs]
        assert types == ["inline", "display"]

    def test_no_math(self):
        """No math in text -> empty list."""
        assert extract_math("Plain text without LaTeX.") == []

    def test_dollar_sign_not_math(self):
        """Prices ($5.00) not treated as LaTeX."""
        exprs = extract_math("It costs $5.00 and $10.00.")
        assert len(exprs) == 0


# ============================================================================
# extract_stats
# ============================================================================


class TestExtractStats:
    def test_pvalue_simple(self):
        """p = 0.03 extracted correctly."""
        stats = extract_stats("The result was significant (p = 0.03).")
        pvals = [s for s in stats if s["type"] == "p-value"]
        assert len(pvals) >= 1
        assert pvals[0]["value"] == pytest.approx(0.03)

    def test_pvalue_inequality(self):
        """p < 0.001 extracted correctly."""
        stats = extract_stats("p < 0.001 was observed.")
        pvals = [s for s in stats if s["type"] == "p-value"]
        assert len(pvals) >= 1
        assert pvals[0]["value"] == pytest.approx(0.001)
        assert pvals[0]["comparison"] == "<"

    def test_fold_change(self):
        """fold change = 2.5 extracted."""
        stats = extract_stats("The fold change = 2.5 was observed.")
        fcs = [s for s in stats if s["type"] == "fold-change"]
        assert len(fcs) >= 1
        assert fcs[0]["value"] == pytest.approx(2.5)

    def test_log2fc(self):
        """log2FC = -2.5 extracted (negative is valid)."""
        stats = extract_stats("log2FC = -2.5 indicates downregulation.")
        logs = [s for s in stats if s["type"] == "log2FC"]
        assert len(logs) >= 1
        assert logs[0]["value"] == pytest.approx(-2.5)

    def test_percentage(self):
        """45.3% extracted correctly."""
        stats = extract_stats("Response rate was 45.3%.")
        pcts = [s for s in stats if s["type"] == "percentage"]
        assert len(pcts) >= 1
        assert pcts[0]["value"] == pytest.approx(45.3)

    def test_confidence_interval_bracket(self):
        """[1.2, 4.8] extracted correctly."""
        stats = extract_stats("The 95% CI [1.2, 4.8] was reported.")
        cis = [s for s in stats if s["type"] == "confidence-interval"]
        assert len(cis) >= 1
        assert cis[0]["lower"] == pytest.approx(1.2)
        assert cis[0]["upper"] == pytest.approx(4.8)

    def test_confidence_interval_paren(self):
        """(0.5 – 1.3) extracted correctly."""
        stats = extract_stats("Effect size (0.5 – 1.3).")
        cis = [s for s in stats if s["type"] == "confidence-interval"]
        assert len(cis) >= 1
        assert cis[0]["lower"] == pytest.approx(0.5)
        assert cis[0]["upper"] == pytest.approx(1.3)

    def test_sample_size(self):
        """n = 30 extracted correctly."""
        stats = extract_stats("n = 30 participants completed the study.")
        ns = [s for s in stats if s["type"] == "sample-size"]
        assert len(ns) >= 1
        assert ns[0]["value"] == 30

    def test_no_stats(self):
        """No stats in text -> empty list."""
        assert extract_stats("This text has no numbers.") == []


# ============================================================================
# verify_latex_syntax
# ============================================================================


class TestVerifyLatexSyntax:
    def test_valid_latex(self):
        """Simple valid LaTeX has no syntax issues."""
        issues = verify_latex_syntax(r"x^2 + y^2 = 1")
        assert issues == []

    def test_unmatched_braces(self):
        """a^{2+3 has unmatched opening brace."""
        issues = verify_latex_syntax(r"a^{2 + 3")
        brace_issues = [i for i in issues if "brace" in i.lower()]
        assert len(brace_issues) >= 1

    def test_empty_expression(self):
        """Empty string flagged."""
        issues = verify_latex_syntax("")
        assert any("empty" in i.lower() for i in issues)

    def test_balanced_braces_valid(self):
        """\\frac{1}{2} has balanced braces."""
        issues = verify_latex_syntax(r"\frac{1}{2}")
        brace_issues = [i for i in issues if "brace" in i.lower()]
        assert len(brace_issues) == 0

    def test_nested_braces(self):
        """Nested braces \\sqrt{\\frac{a}{b}} are valid."""
        issues = verify_latex_syntax(r"\sqrt{\frac{a}{b}}")
        brace_issues = [i for i in issues if "brace" in i.lower()]
        assert len(brace_issues) == 0


# ============================================================================
# verify_pvalue
# ============================================================================


class TestVerifyPvalue:
    def test_valid_pvalue(self):
        """p=0.03 is a plausible p-value."""
        issues = verify_pvalue({"value": 0.03, "comparison": "="})
        assert issues == []

    def test_impossible_pvalue_negative(self):
        """p=-0.5 is impossible — outside [0, 1]."""
        issues = verify_pvalue({"value": -0.5, "comparison": "="})
        assert len(issues) >= 1
        assert any("cannot be negative" in i.lower() for i in issues)

    def test_impossible_pvalue_greater_than_one(self):
        """p=1.5 is impossible — outside [0, 1]."""
        issues = verify_pvalue({"value": 1.5, "comparison": "="})
        assert len(issues) >= 1
        assert any("cannot exceed" in i.lower() for i in issues)

    def test_pvalue_at_boundary_zero(self):
        """p=0.0 is valid."""
        issues = verify_pvalue({"value": 0.0, "comparison": "="})
        assert issues == []

    def test_pvalue_at_boundary_one(self):
        """p=1.0 is valid."""
        issues = verify_pvalue({"value": 1.0, "comparison": "="})
        assert issues == []


# ============================================================================
# verify_fold_change
# ============================================================================


class TestVerifyFoldChange:
    def test_valid_fold_change(self):
        """FC=2.5 is valid."""
        issues = verify_fold_change({"value": 2.5})
        assert issues == []

    def test_zero_fold_change_flagged(self):
        """FC=0.0 flagged."""
        issues = verify_fold_change({"value": 0.0})
        assert len(issues) >= 1

    def test_negative_fold_change_flagged(self):
        """FC=-1.0 flagged."""
        issues = verify_fold_change({"value": -1.0})
        assert len(issues) >= 1


# ============================================================================
# verify_percentage
# ============================================================================


class TestVerifyPercentage:
    def test_valid_percentage(self):
        """45.3% is valid."""
        issues = verify_percentage({"value": 45.3})
        assert issues == []

    def test_percentage_above_100(self):
        """150% flagged."""
        issues = verify_percentage({"value": 150.0})
        assert len(issues) >= 1

    def test_percentage_negative(self):
        """-5% flagged."""
        issues = verify_percentage({"value": -5.0})
        assert len(issues) >= 1


# ============================================================================
# verify_confidence_interval
# ============================================================================


class TestVerifyConfidenceInterval:
    def test_valid_ci(self):
        """CI [1.2, 4.8] — lower <= upper, not zero-width."""
        issues = verify_confidence_interval({"lower": 1.2, "upper": 4.8})
        assert issues == []

    def test_invalid_ci_lower_greater_than_upper(self):
        """CI [5, 2] — lower > upper flagged."""
        issues = verify_confidence_interval({"lower": 5.0, "upper": 2.0})
        assert len(issues) >= 1
        assert any("greater than" in i.lower()
                   or "lower bound > upper" in i.lower()
                   for i in issues)

    def test_zero_width_ci(self):
        """CI [3, 3] — zero width flagged."""
        issues = verify_confidence_interval({"lower": 3.0, "upper": 3.0})
        zero_width = [i for i in issues if "zero-width" in i.lower()]
        assert len(zero_width) >= 1


# ============================================================================
# verify_math — full pipeline
# ============================================================================


class TestVerifyMath:
    def test_plain_text(self):
        """Plain text produces empty results."""
        result = verify_math("This is a plain sentence.")
        assert result["text_length"] == 25
        assert result["math_expressions"] == []
        assert result["statistical_claims"] == []

    def test_valid_pvalue_overall(self):
        """Pipeline: p=0.03 should not be flagged."""
        result = verify_math("The result was significant (p = 0.03).")
        flagged_pvals = [
            c
            for c in result["statistical_claims"]
            if c["type"] == "p-value" and c["issues"]
        ]
        assert len(flagged_pvals) == 0
        # At least one p-value should be verified
        verified_pvals = [
            c
            for c in result["statistical_claims"]
            if c["type"] == "p-value" and not c["issues"]
        ]
        assert len(verified_pvals) >= 1

    def test_impossible_pvalue_negative_pipeline(self):
        """Pipeline: p=-0.5 should be flagged."""
        result = verify_math("The p-value = -0.5 was reported.")
        flagged_pvals = [
            c
            for c in result["statistical_claims"]
            if c["type"] == "p-value" and c["issues"]
        ]
        assert len(flagged_pvals) >= 1

    def test_impossible_pvalue_over_one(self):
        """Pipeline: p=1.5 should be flagged."""
        result = verify_math("The p-value = 1.5 was reported.")
        flagged_pvals = [
            c
            for c in result["statistical_claims"]
            if c["type"] == "p-value" and c["issues"]
        ]
        assert len(flagged_pvals) >= 1

    def test_valid_ci_pipeline(self):
        """CI [1.2, 4.8] should not be flagged."""
        result = verify_math("The 95% CI [1.2, 4.8] was observed.")
        flagged_cis = [
            c
            for c in result["statistical_claims"]
            if c["type"] == "confidence-interval" and c["issues"]
        ]
        assert len(flagged_cis) == 0

    def test_invalid_ci_pipeline(self):
        """CI [5, 2] should be flagged (lower > upper)."""
        result = verify_math("The CI [5, 2] was reported.")
        flagged_cis = [
            c
            for c in result["statistical_claims"]
            if c["type"] == "confidence-interval" and c["issues"]
        ]
        assert len(flagged_cis) >= 1

    def test_log2fc_negative_valid(self):
        """Negative log2FC = -2.5 is valid (downregulation), not flagged."""
        result = verify_math("The log2FC = -2.5 indicates downregulation.")
        flagged_logs = [
            c
            for c in result["statistical_claims"]
            if c["type"] == "log2FC" and c["issues"]
        ]
        assert len(flagged_logs) == 0

    def test_latex_unmatched_braces_pipeline(self):
        """LaTeX with unmatched braces flagged."""
        result = verify_math(r"The expression $a^{2 + 3$ is broken.")
        broken = [e for e in result["math_expressions"] if e["issues"]]
        assert len(broken) >= 1

    def test_empty_math_expression_pipeline(self):
        """Empty math expression $$ $$ flagged."""
        result = verify_math("An empty expression: $$ $$.")
        broken = [e for e in result["math_expressions"] if e["issues"]]
        assert len(broken) >= 1

    def test_mixed_pipeline_counts(self):
        """Combination: one valid p-value, one invalid CI."""
        result = verify_math(
            "p = 0.03 was significant, but CI [5, 2] is suspicious."
        )
        assert result["verified"] >= 1
        assert result["flagged"] >= 1
        assert result["verified"] + result["flagged"] == (
            len(result["math_expressions"]) + len(result["statistical_claims"])
        )

    def test_timestamp_format(self):
        """Timestamp is ISO-8601 formatted."""
        result = verify_math("Hello.")
        assert "T" in result["timestamp"]  # ISO-8601 format


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    def test_very_small_pvalue(self):
        """Scientific notation p-value (1.5e-5)."""
        stats = extract_stats("p = 1.5e-5 was detected.")
        pvals = [s for s in stats if s["type"] == "p-value"]
        assert len(pvals) >= 1
        assert pvals[0]["value"] == pytest.approx(1.5e-5)

    def test_pvalue_no_space(self):
        """p=0.03 without spaces."""
        stats = extract_stats("p=0.03")
        pvals = [s for s in stats if s["type"] == "p-value"]
        assert len(pvals) >= 1
        assert pvals[0]["value"] == pytest.approx(0.03)

    def test_fc_vs_log2fc_separate(self):
        """FC and log2FC are separate claim types."""
        stats = extract_stats("FC = 1.5 and log2FC = -1.2")
        types = {s["type"] for s in stats}
        assert "fold-change" in types
        assert "log2FC" in types

    def test_display_math_with_braces(self):
        """Display math with balanced braces is valid."""
        issues = verify_latex_syntax(r"\frac{1}{2}")
        assert issues == []

    def test_pvalue_negative_extracted_and_flagged(self):
        """p = -0.5 is extracted and flagged by verify_pvalue."""
        stats = extract_stats("p = -0.5")
        pvals = [s for s in stats if s["type"] == "p-value"]
        assert len(pvals) >= 1
        assert pvals[0]["value"] == pytest.approx(-0.5)
        issues = verify_pvalue(pvals[0])
        assert len(issues) >= 1
