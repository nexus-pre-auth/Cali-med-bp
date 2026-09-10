"""
Rule Matcher — matches extracted project conditions against the HCAI rules dataset.

Each rule in hcai_rules.json has:
  {
    "id": "RULE-001",
    "discipline": "Infection Control",
    "trigger_occupancies": ["Occupied Hospital", "Acute Care Hospital"],
    "trigger_systems": [],           // empty = applies to all
    "trigger_rooms": [],
    "trigger_seismic_zones": [],
    "description": "...",
    "violation_template": "...",
    "fix_template": "...",
    "code_references": ["Title 24 Part 2 Section 420.3", "PIN 25-04"],
    "severity_override": null        // null = auto-scored
  }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.parser.condition_extractor import ProjectConditions
from src.engine.severity_scorer import Severity, score_violation


@dataclass
class MatchedViolation:
    rule_id: str
    discipline: str
    severity: Severity
    trigger_condition: str
    description: str
    violation_text: str
    fix_text: str
    code_references: list[str] = field(default_factory=list)
    # Populated later by RAG layer
    ahj_comment: Optional[str] = None
    rag_citations: list[str] = field(default_factory=list)
    # --- Provenance (Phase 4) ---------------------------------------------
    # These fields exist to let a user answer "why was this flagged?" without
    # fabricating regulatory authority. `jurisdiction` reflects the scope of
    # this rules dataset (California/HCAI only). `code_family` and
    # `citation_verified` are derived directly from `code_references` — if a
    # rule has no code reference, we say so explicitly rather than inventing
    # one.
    jurisdiction: str = "California (HCAI)"
    code_family: Optional[str] = None
    citation_verified: bool = False
    confidence: str = "auto_scored"  # "rule_override" when severity is hard-coded in the rule

    def provenance(self) -> dict:
        """Structured provenance for 'why was this flagged?' explanations."""
        return {
            "finding_id": None,  # assigned by the caller/report layer once persisted
            "rule_id": self.rule_id,
            "discipline": self.discipline,
            "severity": self.severity.value,
            "jurisdiction": self.jurisdiction,
            "code_family": self.code_family,
            "source_reference": self.code_references,
            "citation_verified": self.citation_verified,
            "trigger_condition": self.trigger_condition,
            "requirement": self.description,
            "project_evidence": self.trigger_condition,
            "recommended_action": self.fix_text,
            "confidence": self.confidence,
        }


_KNOWN_CODE_FAMILIES = ("Title 24", "CBC", "CMC", "CPC", "CEC", "NFPA", "ASHRAE", "PIN", "CAN")


def _infer_code_family(code_references: list[str]) -> Optional[str]:
    """Best-effort classification of the code family from a citation string.

    Returns None (never a guess) when no known family prefix is found, so we
    never fabricate a citation's authority.
    """
    for ref in code_references:
        for family in _KNOWN_CODE_FAMILIES:
            if family.lower() in ref.lower():
                return family
    return None


class RuleMatcher:
    """Loads HCAI rules and returns violations that apply to the given conditions."""

    def __init__(self, rules_file: str | Path) -> None:
        rules_path = Path(rules_file)
        if not rules_path.exists():
            raise FileNotFoundError(f"Rules file not found: {rules_file}")
        with open(rules_path) as f:
            self._rules: list[dict] = json.load(f)

    def match(self, conditions: ProjectConditions) -> list[MatchedViolation]:
        violations: list[MatchedViolation] = []

        for rule in self._rules:
            if not self._applies(rule, conditions):
                continue

            trigger = conditions.occupancy_type or "General Healthcare"
            description = rule.get("description", "")
            discipline  = rule.get("discipline", "General")

            # Resolve severity
            if rule.get("severity_override"):
                severity = Severity(rule["severity_override"])
            else:
                severity = score_violation(
                    discipline=discipline,
                    trigger_condition=trigger,
                    code_section=" ".join(rule.get("code_references", [])),
                    description=description,
                )

            code_refs = rule.get("code_references", [])
            violations.append(
                MatchedViolation(
                    rule_id=rule["id"],
                    discipline=discipline,
                    severity=severity,
                    trigger_condition=trigger,
                    description=description,
                    violation_text=self._render(rule.get("violation_template", description), conditions),
                    fix_text=self._render(rule.get("fix_template", "Refer to code section."), conditions),
                    code_references=code_refs,
                    code_family=_infer_code_family(code_refs),
                    citation_verified=bool(code_refs),
                    confidence="rule_override" if rule.get("severity_override") else "auto_scored",
                )
            )

        # Sort: Critical → High → Medium → Low
        violations.sort(key=lambda v: v.severity.order)
        return violations

    # ------------------------------------------------------------------
    def _applies(self, rule: dict, c: ProjectConditions) -> bool:
        # Occupancy filter
        occ_filter = rule.get("trigger_occupancies", [])
        if occ_filter and c.occupancy_type not in occ_filter:
            return False

        # System filter (any match = include)
        sys_filter = rule.get("trigger_systems", [])
        if sys_filter:
            all_systems = c.hvac_systems + c.plumbing_systems + c.electrical_systems + c.medical_gas_systems
            all_systems_lower = [s.lower() for s in all_systems]
            if not any(sf.lower() in all_systems_lower for sf in sys_filter):
                return False

        # Room filter
        room_filter = rule.get("trigger_rooms", [])
        if room_filter:
            rooms_lower = [r.lower() for r in c.room_types]
            if not any(rf.lower() in rooms_lower for rf in room_filter):
                return False

        # Seismic zone filter
        seismic_filter = rule.get("trigger_seismic_zones", [])
        if seismic_filter and c.seismic.seismic_zone not in seismic_filter:
            return False

        return True

    def _render(self, template: str, c: ProjectConditions) -> str:
        """Simple template substitution for rule text."""
        replacements = {
            "{occupancy}": c.occupancy_type or "the facility",
            "{construction_type}": c.construction_type or "the building",
            "{seismic_zone}": c.seismic.seismic_zone or "N/A",
            "{county}": c.county or "the county",
            "{city}": c.city or "the jurisdiction",
        }
        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result
