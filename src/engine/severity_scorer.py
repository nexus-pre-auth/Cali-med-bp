"""
Severity Scorer — assigns Critical / High / Medium / Low to each violation.

Scoring is based on:
  - Life-safety impact
  - Patient vulnerability
  - Regulatory mandate level (mandatory vs. advisory)
  - Seismic / structural risk
  - Infection-control consequences
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH     = "High"
    MEDIUM   = "Medium"
    LOW      = "Low"

    @property
    def order(self) -> int:
        return {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}[self.value]

    def __lt__(self, other: "Severity") -> bool:
        return self.order < other.order


# Keywords that escalate severity
_CRITICAL_TRIGGERS = [
    "life safety", "fire protection", "sprinkler", "emergency power",
    "essential electrical", "EES", "medical gas", "oxygen", "seismic bracing",
    "isolation room", "infection control", "structural", "egress", "exit",
    "patient safety", "critical branch", "life safety branch",
]

_HIGH_TRIGGERS = [
    "HVAC", "ventilation", "air changes", "pressure differential",
    "operating room", "ICU", "NICU", "PACU", "surgery", "sterilization",
    "electrical", "generator", "transfer switch", "alarm system",
]

_MEDIUM_TRIGGERS = [
    "plumbing", "water heater", "backflow", "signage", "accessibility",
    "ADA", "door hardware", "corridor width", "storage",
]


def score_violation(
    discipline: str,
    trigger_condition: str,
    code_section: str,
    description: str,
) -> Severity:
    """
    Compute severity for a single violation.

    Parameters
    ----------
    discipline         : e.g. "Infection Control", "Structural / Seismic"
    trigger_condition  : e.g. "Occupied Hospital"
    code_section       : e.g. "Title 24 Part 2"
    description        : free-text violation description
    """
    combined = " ".join([discipline, trigger_condition, code_section, description]).lower()

    if any(t.lower() in combined for t in _CRITICAL_TRIGGERS):
        return Severity.CRITICAL

    if any(t.lower() in combined for t in _HIGH_TRIGGERS):
        return Severity.HIGH

    if any(t.lower() in combined for t in _MEDIUM_TRIGGERS):
        return Severity.MEDIUM

    return Severity.LOW
