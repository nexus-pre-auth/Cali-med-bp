"""
Validation Checklist — measures engine accuracy across extraction, detection, and scoring.

Used to benchmark the engine against known AHJ review findings (ground truth).
Targets 85%+ match with real AHJ comments per the system spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.engine.severity_scorer import Severity
from src.rag.generator import EnrichedViolation


@dataclass
class ChecklistItem:
    category: str           # "extraction" | "detection" | "severity" | "citation"
    description: str
    passed: bool
    detail: str = ""
    score: float = 0.0      # 0.0 – 1.0


@dataclass
class ValidationResult:
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.items:
            return 0.0
        return sum(i.score for i in self.items) / len(self.items)

    @property
    def passed_count(self) -> int:
        return sum(1 for i in self.items if i.passed)

    @property
    def total_count(self) -> int:
        return len(self.items)

    def summary(self) -> str:
        pct = self.overall_score * 100
        return (
            f"Validation: {self.passed_count}/{self.total_count} checks passed "
            f"({pct:.1f}% overall accuracy)"
        )

    def by_category(self) -> dict[str, float]:
        categories: dict[str, list[float]] = {}
        for item in self.items:
            categories.setdefault(item.category, []).append(item.score)
        return {cat: sum(scores) / len(scores) for cat, scores in categories.items()}


class ComplianceChecklist:
    """
    Runs a structured validation checklist against engine outputs.

    Parameters
    ----------
    ground_truth_file : Optional path to a JSON file with known violations.
        Format:
        [
          {
            "rule_id": "RULE-001",
            "severity": "Critical",
            "discipline": "Infection Control",
            "keywords_in_ahj": ["isolation", "negative pressure"]
          },
          ...
        ]
    """

    def __init__(self, ground_truth_file: str | Path | None = None) -> None:
        self._ground_truth: list[dict] = []
        if ground_truth_file:
            p = Path(ground_truth_file)
            if p.exists():
                with open(p) as f:
                    self._ground_truth = json.load(f)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        enriched: list[EnrichedViolation],
        extracted_conditions_summary: dict,
    ) -> ValidationResult:
        result = ValidationResult()

        # 1. Extraction checks
        result.items += self._check_extraction(extracted_conditions_summary)

        # 2. Detection checks (rule coverage)
        result.items += self._check_detection(enriched)

        # 3. Severity scoring checks
        result.items += self._check_severity(enriched)

        # 4. Citation / RAG checks
        result.items += self._check_citations(enriched)

        # 5. Ground-truth match (if available)
        if self._ground_truth:
            result.items += self._check_ground_truth(enriched)

        return result

    # ------------------------------------------------------------------
    # Check categories
    # ------------------------------------------------------------------

    def _check_extraction(self, summary: dict) -> list[ChecklistItem]:
        items = []

        has_occupancy = bool(summary.get("occupancy_type"))
        items.append(ChecklistItem(
            category="extraction",
            description="Occupancy type identified",
            passed=has_occupancy,
            score=1.0 if has_occupancy else 0.0,
            detail=summary.get("occupancy_type") or "Not found",
        ))

        has_seismic = bool(summary.get("seismic_zone") or summary.get("sds"))
        items.append(ChecklistItem(
            category="extraction",
            description="Seismic data extracted",
            passed=has_seismic,
            score=1.0 if has_seismic else 0.5,  # Partial credit — not all projects have seismic data
            detail=f"Zone={summary.get('seismic_zone')}, SDS={summary.get('sds')}",
        ))

        has_systems = bool(
            summary.get("hvac_count", 0) or
            summary.get("electrical_count", 0) or
            summary.get("plumbing_count", 0)
        )
        items.append(ChecklistItem(
            category="extraction",
            description="MEP systems identified",
            passed=has_systems,
            score=1.0 if has_systems else 0.0,
            detail=(
                f"HVAC={summary.get('hvac_count',0)}, "
                f"Electrical={summary.get('electrical_count',0)}, "
                f"Plumbing={summary.get('plumbing_count',0)}"
            ),
        ))

        has_rooms = bool(summary.get("room_count", 0))
        items.append(ChecklistItem(
            category="extraction",
            description="Room types identified",
            passed=has_rooms,
            score=1.0 if has_rooms else 0.0,
            detail=f"{summary.get('room_count', 0)} room types found",
        ))

        return items

    def _check_detection(self, enriched: list[EnrichedViolation]) -> list[ChecklistItem]:
        items = []

        has_violations = len(enriched) > 0
        items.append(ChecklistItem(
            category="detection",
            description="Violations detected",
            passed=has_violations,
            score=1.0 if has_violations else 0.0,
            detail=f"{len(enriched)} violations found",
        ))

        disciplines = {ev.violation.discipline for ev in enriched}
        multi_discipline = len(disciplines) >= 2
        items.append(ChecklistItem(
            category="detection",
            description="Multi-discipline coverage (≥2 disciplines)",
            passed=multi_discipline,
            score=min(1.0, len(disciplines) / 4),
            detail=f"Disciplines: {', '.join(sorted(disciplines))}",
        ))

        has_critical = any(ev.violation.severity == Severity.CRITICAL for ev in enriched)
        items.append(ChecklistItem(
            category="detection",
            description="Critical violations flagged",
            passed=has_critical,
            score=1.0 if has_critical else 0.7,  # Not failing — may be compliant
            detail="Critical severity issues detected" if has_critical else "No critical violations",
        ))

        return items

    def _check_severity(self, enriched: list[EnrichedViolation]) -> list[ChecklistItem]:
        items = []

        # All violations have a valid severity
        all_valid = all(ev.violation.severity.value in [s.value for s in Severity] for ev in enriched)
        items.append(ChecklistItem(
            category="severity",
            description="All violations have valid severity scores",
            passed=all_valid,
            score=1.0 if all_valid else 0.0,
        ))

        # Sorted correctly (Critical first)
        if len(enriched) > 1:
            sorted_correctly = all(
                enriched[i].violation.severity.order <= enriched[i+1].violation.severity.order
                for i in range(len(enriched) - 1)
            )
            items.append(ChecklistItem(
                category="severity",
                description="Violations sorted by severity (Critical first)",
                passed=sorted_correctly,
                score=1.0 if sorted_correctly else 0.0,
            ))

        return items

    def _check_citations(self, enriched: list[EnrichedViolation]) -> list[ChecklistItem]:
        items = []

        with_citations = [ev for ev in enriched if ev.citations]
        citation_rate = len(with_citations) / len(enriched) if enriched else 0.0
        items.append(ChecklistItem(
            category="citation",
            description="Violations include code citations",
            passed=citation_rate >= 0.8,
            score=citation_rate,
            detail=f"{len(with_citations)}/{len(enriched)} violations have citations",
        ))

        title24_refs = sum(
            1 for ev in enriched
            if any("title 24" in c.lower() or "cbc" in c.lower() for c in ev.citations)
        )
        t24_rate = title24_refs / len(enriched) if enriched else 0.0
        items.append(ChecklistItem(
            category="citation",
            description="Title 24 / CBC references present",
            passed=t24_rate >= 0.5,
            score=t24_rate,
            detail=f"{title24_refs}/{len(enriched)} violations reference Title 24/CBC",
        ))

        return items

    def _check_ground_truth(self, enriched: list[EnrichedViolation]) -> list[ChecklistItem]:
        """Compare against known violations (ground truth)."""
        items = []
        found_rule_ids = {ev.violation.rule_id for ev in enriched}
        gt_rule_ids = {gt["rule_id"] for gt in self._ground_truth if "rule_id" in gt}

        if gt_rule_ids:
            matched = found_rule_ids & gt_rule_ids
            recall = len(matched) / len(gt_rule_ids)
            items.append(ChecklistItem(
                category="ground_truth",
                description="Rule recall vs. ground truth",
                passed=recall >= 0.85,
                score=recall,
                detail=f"Matched {len(matched)}/{len(gt_rule_ids)} expected rules ({recall*100:.1f}%)",
            ))

        # Severity match
        severity_matches = 0
        for gt in self._ground_truth:
            if "rule_id" not in gt or "severity" not in gt:
                continue
            for ev in enriched:
                if ev.violation.rule_id == gt["rule_id"]:
                    if ev.violation.severity.value == gt["severity"]:
                        severity_matches += 1
                    break

        if self._ground_truth:
            sev_rate = severity_matches / len(self._ground_truth)
            items.append(ChecklistItem(
                category="ground_truth",
                description="Severity accuracy vs. ground truth",
                passed=sev_rate >= 0.85,
                score=sev_rate,
                detail=f"{severity_matches}/{len(self._ground_truth)} severity levels match ({sev_rate*100:.1f}%)",
            ))

        # AHJ keyword match
        keyword_hits = 0
        keyword_total = 0
        for gt in self._ground_truth:
            for kw in gt.get("keywords_in_ahj", []):
                keyword_total += 1
                for ev in enriched:
                    if ev.violation.rule_id == gt.get("rule_id") and kw.lower() in ev.ahj_comment.lower():
                        keyword_hits += 1
                        break

        if keyword_total:
            kw_rate = keyword_hits / keyword_total
            items.append(ChecklistItem(
                category="ground_truth",
                description="AHJ comment keyword match",
                passed=kw_rate >= 0.85,
                score=kw_rate,
                detail=f"{keyword_hits}/{keyword_total} expected keywords present ({kw_rate*100:.1f}%)",
            ))

        return items
