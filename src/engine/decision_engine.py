"""
Decision Engine — Step 2: Intelligent Decision Mapping.

Orchestrates the full pipeline:
  1. Receives extracted ProjectConditions
  2. Loads FGI baseline rules (applies to all states)
  3. Loads state-specific AHJ rules (based on conditions.state)
  4. Runs RuleMatcher against combined ruleset
  5. Returns prioritized MatchedViolation list
"""

from __future__ import annotations

import json
from pathlib import Path

from src.parser.condition_extractor import ProjectConditions
from src.engine.rule_matcher import RuleMatcher, MatchedViolation
from src.engine.severity_scorer import Severity
import config


# Maps full state names → 2-letter codes for lookup in STATE_AHJ_MAP
_STATE_NAME_TO_CODE: dict[str, str] = {
    v["state_name"].lower(): k for k, v in config.STATE_AHJ_MAP.items()
}


def _state_code(state: str) -> str:
    """Normalise a state name or code to its 2-letter code (e.g. 'California' → 'CA')."""
    s = state.strip()
    if len(s) == 2:
        return s.upper()
    return _STATE_NAME_TO_CODE.get(s.lower(), "CA")


class DecisionEngine:
    """
    Core compliance decision engine.

    Usage
    -----
    engine = DecisionEngine()
    violations = engine.evaluate(conditions)
    """

    def __init__(self, rules_file: str | Path | None = None) -> None:
        # Legacy single-file override (used by tests and --rules flag)
        self._rules_file_override = Path(rules_file) if rules_file else None

    def evaluate(self, conditions: ProjectConditions) -> list[MatchedViolation]:
        """
        Evaluate project conditions and return all applicable violations,
        sorted by severity (Critical first).
        """
        rules = self._load_rules(conditions)
        matcher = RuleMatcher(rules)
        return matcher.match(conditions)

    def summary(self, violations: list[MatchedViolation]) -> dict:
        """Return a severity-count summary dict."""
        counts = {s.value: 0 for s in Severity}
        for v in violations:
            counts[v.severity.value] += 1
        return {
            "total": len(violations),
            "by_severity": counts,
        }

    # ------------------------------------------------------------------
    # Rule loading
    # ------------------------------------------------------------------

    def _load_rules(self, conditions: ProjectConditions) -> list[dict]:
        """Return combined rule list: FGI baseline + state-specific rules."""
        if self._rules_file_override:
            return self._load_json(self._rules_file_override)

        rules: list[dict] = []

        # 1. FGI national baseline (applies to all states)
        if config.FGI_RULES_FILE.exists():
            rules.extend(self._load_json(config.FGI_RULES_FILE))

        # 2. State-specific rules
        state_code = _state_code(conditions.state or "CA")
        if state_code == "CA":
            # California uses the original HCAI rules file
            if config.HCAI_RULES_FILE.exists():
                rules.extend(self._load_json(config.HCAI_RULES_FILE))
        else:
            ahj_entry = config.STATE_AHJ_MAP.get(state_code)
            if ahj_entry:
                state_file = config.STATES_RULES_DIR / ahj_entry["file"]
                if state_file.exists():
                    rules.extend(self._load_json(state_file))

        # Deduplicate by rule id (FGI rules may overlap state rules)
        seen: set[str] = set()
        unique: list[dict] = []
        for rule in rules:
            rid = rule.get("id", "")
            if rid not in seen:
                seen.add(rid)
                unique.append(rule)

        return unique

    @staticmethod
    def _load_json(path: Path) -> list[dict]:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return []
