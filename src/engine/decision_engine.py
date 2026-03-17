"""
Decision Engine — Step 2: Intelligent Decision Mapping.

Orchestrates the full pipeline:
  1. Receives extracted ProjectConditions
  2. Runs RuleMatcher against HCAI dataset
  3. Returns prioritized MatchedViolation list
"""

from __future__ import annotations

from pathlib import Path

from src.parser.condition_extractor import ProjectConditions
from src.engine.rule_matcher import RuleMatcher, MatchedViolation
from src.engine.severity_scorer import Severity
import config


class DecisionEngine:
    """
    Core compliance decision engine.

    Usage
    -----
    engine = DecisionEngine()
    violations = engine.evaluate(conditions)
    """

    def __init__(self, rules_file: str | Path | None = None) -> None:
        rules_path = Path(rules_file) if rules_file else config.HCAI_RULES_FILE
        self._matcher = RuleMatcher(rules_path)

    def evaluate(self, conditions: ProjectConditions) -> list[MatchedViolation]:
        """
        Evaluate project conditions and return all applicable violations,
        sorted by severity (Critical first).
        """
        violations = self._matcher.match(conditions)
        return violations

    def summary(self, violations: list[MatchedViolation]) -> dict:
        """Return a severity-count summary dict."""
        counts = {s.value: 0 for s in Severity}
        for v in violations:
            counts[v.severity.value] += 1
        return {
            "total": len(violations),
            "by_severity": counts,
        }
