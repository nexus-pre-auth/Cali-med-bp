"""
Confidence Scorer — quantifies how certain the engine is about its outputs.

Three independent confidence dimensions:
  1. Extraction confidence  — how fully the condition extractor populated fields
  2. Rule-match confidence  — keyword overlap between project text and matched rule
  3. Overall confidence     — composite score used in reports

Scores are in the range [0.0, 1.0].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.parser.condition_extractor import ProjectConditions
from src.engine.rule_matcher import MatchedViolation


@dataclass
class ConfidenceReport:
    extraction: float        # 0.0 – 1.0
    rule_match: float        # 0.0 – 1.0
    overall: float           # weighted composite
    detail: dict[str, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.overall >= 0.80:
            return "High"
        if self.overall >= 0.55:
            return "Medium"
        return "Low"


class ConfidenceScorer:
    """Assigns confidence scores to extracted conditions and matched violations."""

    # Weights for composite score
    _EXTRACTION_WEIGHT = 0.5
    _MATCH_WEIGHT = 0.5

    # Fields that contribute to extraction confidence
    _EXTRACTION_FIELDS = [
        "occupancy_type",
        "construction_type",
        "sprinklered",
        "licensed_beds",
        "county",
        "city",
    ]

    _EXTRACTION_SYSTEM_FIELDS = [
        "hvac_systems",
        "electrical_systems",
        "plumbing_systems",
        "medical_gas_systems",
        "room_types",
    ]

    _SEISMIC_FIELDS = [
        "seismic_zone",
        "sds",
        "sd1",
        "importance_factor",
    ]

    def score_extraction(self, conditions: ProjectConditions) -> float:
        """
        Returns a float [0, 1] representing completeness of extracted data.
        Each populated field contributes equally.
        """
        total = 0
        filled = 0

        # Scalar fields
        for f in self._EXTRACTION_FIELDS:
            total += 1
            if getattr(conditions, f, None) is not None:
                filled += 1

        # List fields — partial credit for non-empty lists
        for f in self._EXTRACTION_SYSTEM_FIELDS:
            total += 1
            lst = getattr(conditions, f, [])
            if lst:
                filled += 1

        # Seismic sub-fields
        for f in self._SEISMIC_FIELDS:
            total += 1
            if getattr(conditions.seismic, f, None) is not None:
                filled += 1

        return filled / total if total else 0.0

    def score_rule_match(
        self,
        violation: MatchedViolation,
        full_text: str,
    ) -> float:
        """
        Returns [0, 1] based on how many trigger keywords from the rule
        description appear in the project text.
        """
        if not full_text:
            return 0.5  # No text to compare against — neutral

        text_lower = full_text.lower()

        # Build keyword pool from description + code refs
        candidate_text = " ".join([
            violation.description,
            violation.discipline,
            " ".join(violation.code_references),
        ])

        # Split into meaningful tokens (3+ chars, exclude stop words)
        _STOP = {"the", "and", "for", "are", "not", "must", "shall", "with",
                  "per", "all", "any", "has", "have", "been", "this", "that"}
        keywords = [
            w.lower().strip(".,;:()")
            for w in candidate_text.split()
            if len(w) >= 3 and w.lower() not in _STOP
        ]

        if not keywords:
            return 0.5

        hits = sum(1 for kw in keywords if kw in text_lower)
        return min(1.0, hits / len(keywords))

    def score_violations(
        self,
        violations: list[MatchedViolation],
        full_text: str,
        conditions: Optional[ProjectConditions] = None,
    ) -> list[tuple[MatchedViolation, ConfidenceReport]]:
        """
        Return each violation paired with its ConfidenceReport.
        """
        extraction_score = (
            self.score_extraction(conditions) if conditions else 0.5
        )

        results = []
        for v in violations:
            match_score = self.score_rule_match(v, full_text)
            overall = (
                self._EXTRACTION_WEIGHT * extraction_score
                + self._MATCH_WEIGHT * match_score
            )
            report = ConfidenceReport(
                extraction=extraction_score,
                rule_match=match_score,
                overall=overall,
                detail={
                    "extraction_completeness": round(extraction_score, 3),
                    "keyword_overlap": round(match_score, 3),
                },
            )
            results.append((v, report))

        return results
