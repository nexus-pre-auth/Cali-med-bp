"""
Rule Matcher — matches extracted project conditions against the HCAI rules dataset.

Each rule in hcai_rules.json has:
  {
    "id": "RULE-001",
    "discipline": "Infection Control",
    "trigger_occupancies": ["Occupied Hospital", "Acute Care Hospital"],
    "trigger_systems": [],              // empty = applies to all
    "trigger_rooms": [],
    "trigger_seismic_zones": [],
    "trigger_construction_types": [],   // empty = applies to all construction types
    "min_licensed_beds": null,          // null = no bed-count threshold
    "description": "...",
    "violation_template": "...",
    "fix_template": "...",
    "code_references": ["Title 24 Part 2 Section 420.3", "PIN 25-04"],
    "severity_override": null           // null = auto-scored
  }
"""

from __future__ import annotations

import json
import re
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


class RuleMatcher:
    """Loads HCAI rules and returns violations that apply to the given conditions."""

    def __init__(self, rules_file: str | Path) -> None:
        # Try SQLite store first (persistent, queryable)
        try:
            from src.db.rules_store import get_rules_store
            store = get_rules_store()
            self._rules: list[dict] = store.get_all_active()
            return
        except Exception:
            pass  # Fall back to JSON

        # JSON fallback
        rules_path = Path(rules_file)
        if not rules_path.exists():
            raise FileNotFoundError(f"Rules file not found: {rules_file}")
        with open(rules_path) as f:
            self._rules = json.load(f)

    def match(self, conditions: ProjectConditions) -> list[MatchedViolation]:
        violations: list[MatchedViolation] = []

        for rule in self._rules:
            if not self._applies(rule, conditions):
                continue

            # Build a human-readable trigger string for the report
            trigger_parts = [conditions.occupancy_type or "General Healthcare"]
            if conditions.construction_type:
                trigger_parts.append(conditions.construction_type)
            if conditions.licensed_beds:
                trigger_parts.append(f"{conditions.licensed_beds} beds")
            trigger = ", ".join(trigger_parts)
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

            violations.append(
                MatchedViolation(
                    rule_id=rule["id"],
                    discipline=discipline,
                    severity=severity,
                    trigger_condition=trigger,
                    description=description,
                    violation_text=self._render(rule.get("violation_template", description), conditions),
                    fix_text=self._render(rule.get("fix_template", "Refer to code section."), conditions),
                    code_references=rule.get("code_references", []),
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

        # Construction type filter (any match = include).
        # Use word-boundary regex so "I-A" does not match "II-A".
        ct_filter = rule.get("trigger_construction_types", [])
        if ct_filter and c.construction_type:
            ct_lower = c.construction_type.lower()
            if not any(
                re.search(r"\b" + re.escape(cf.lower()) + r"\b", ct_lower)
                for cf in ct_filter
            ):
                return False

        # Licensed beds threshold
        min_beds = rule.get("min_licensed_beds")
        if min_beds is not None:
            if c.licensed_beds is None or c.licensed_beds < min_beds:
                return False

        # Sprinkler status filter (None = applies regardless)
        req_sprinkled = rule.get("trigger_sprinklered")
        if req_sprinkled is not None and c.sprinklered is not None:
            if bool(req_sprinkled) != c.sprinklered:
                return False

        # Building height threshold
        min_height = rule.get("min_building_height_ft")
        if min_height is not None:
            if c.building_height_ft is None or c.building_height_ft < min_height:
                return False

        # Stories above grade threshold
        min_stories = rule.get("min_stories")
        if min_stories is not None:
            if c.stories_above_grade is None or c.stories_above_grade < min_stories:
                return False

        # County filter (any match = include; empty = all counties)
        # When county filter is set, unknown county does NOT satisfy the rule.
        county_filter = rule.get("trigger_counties", [])
        if county_filter:
            if not c.county or not any(cf.lower() == c.county.lower() for cf in county_filter):
                return False

        # City filter (any match = include; empty = all cities)
        # When city filter is set, unknown city does NOT satisfy the rule.
        city_filter = rule.get("trigger_cities", [])
        if city_filter:
            if not c.city or not any(cf.lower() == c.city.lower() for cf in city_filter):
                return False

        # WUI / Wildfire zone filter — only fires when wui_zone is explicitly True
        if rule.get("trigger_wui"):
            if not c.wui_zone:
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
            "{licensed_beds}": str(c.licensed_beds) if c.licensed_beds else "unknown",
            "{height_ft}": str(int(c.building_height_ft)) if c.building_height_ft else "unknown",
            "{stories}": str(c.stories_above_grade) if c.stories_above_grade else "unknown",
        }
        result = template
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        return result
