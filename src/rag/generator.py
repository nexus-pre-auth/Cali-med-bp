"""
AHJ Comment Generator — Step 3: RAG-Backed Reporting.

Uses Claude API + retrieved regulatory passages to generate:
  - AHJ-style plan review comments
  - Accurate Title 24 / PIN / CAN citations
  - Step-by-step compliance fixes
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

import config
from src.engine.rule_matcher import MatchedViolation
from src.rag.knowledge_base import HCAIKnowledgeBase

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


@dataclass
class EnrichedViolation:
    """A MatchedViolation enriched with RAG-generated AHJ content."""
    violation: MatchedViolation
    ahj_comment: str
    fix_instructions: str
    citations: list[str]
    rag_passages_used: list[str]


_SYSTEM_PROMPT = """You are an expert HCAI (Healthcare Construction Analysis and Inspection) plan reviewer
for California healthcare construction projects. You write AHJ (Authority Having Jurisdiction)-style
plan review comments that are:
- Precise and technically accurate
- Grounded in Title 24 California Building Code, OSHPD/HCAI Policy Intent Notices (PINs),
  and Construction Advisory Notices (CANs)
- Professional and clear, as if written by a senior HCAI engineer
- Actionable — each comment tells the design team exactly what to fix

Format your response as valid JSON with these keys:
{
  "ahj_comment": "...",
  "fix_instructions": "...",
  "citations": ["...", "..."]
}
"""


def _build_user_prompt(
    violation: MatchedViolation,
    rag_passages: list[dict],
) -> str:
    passages_text = "\n\n".join(
        f"[{p['id']}] ({p['metadata'].get('source','')}) {p['text']}"
        for p in rag_passages
    )

    return f"""
VIOLATION IDENTIFIED
====================
Rule ID         : {violation.rule_id}
Discipline      : {violation.discipline}
Severity        : {violation.severity.value}
Trigger         : {violation.trigger_condition}
Description     : {violation.description}
Violation       : {violation.violation_text}
Preliminary Fix : {violation.fix_text}
Code References : {", ".join(violation.code_references)}

RETRIEVED REGULATORY CONTEXT
=============================
{passages_text if passages_text else "(No RAG context available — rely on known standards)"}

TASK
====
Write an HCAI AHJ-style plan review comment for this violation.
Include:
1. ahj_comment  — formal plan review comment (2-4 sentences, AHJ voice)
2. fix_instructions — numbered step-by-step remediation guide
3. citations — list of exact code citations used (e.g. "Title 24 Part 2 Section 420.3.2")

Respond ONLY with the JSON object.
"""


class AHJCommentGenerator:
    """
    Generates AHJ-style comments using RAG context + Claude API.
    Falls back to template-based generation if Claude is unavailable.
    """

    def __init__(
        self,
        knowledge_base: HCAIKnowledgeBase | None = None,
        api_key: str | None = None,
    ) -> None:
        self._kb = knowledge_base
        api_key = api_key or config.ANTHROPIC_API_KEY
        if HAS_ANTHROPIC and api_key:
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            self._client = None

    def enrich(self, violations: list[MatchedViolation]) -> list[EnrichedViolation]:
        """Enrich a list of violations with AHJ comments."""
        enriched = []
        for v in violations:
            ev = self._enrich_one(v)
            enriched.append(ev)
        return enriched

    def _enrich_one(self, violation: MatchedViolation) -> EnrichedViolation:
        # Retrieve RAG context
        query = f"{violation.discipline} {violation.description} {' '.join(violation.code_references)}"
        rag_passages: list[dict] = []
        if self._kb:
            with contextlib.suppress(Exception):
                rag_passages = self._kb.query(query, top_k=config.RAG_TOP_K)

        rag_texts = [p["text"] for p in rag_passages]

        if self._client:
            return self._generate_with_claude(violation, rag_passages, rag_texts)
        else:
            return self._generate_fallback(violation, rag_texts)

    def _generate_with_claude(
        self,
        violation: MatchedViolation,
        rag_passages: list[dict],
        rag_texts: list[str],
    ) -> EnrichedViolation:
        import json as _json

        user_prompt = _build_user_prompt(violation, rag_passages)

        try:
            message = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = message.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = _json.loads(raw)
            return EnrichedViolation(
                violation=violation,
                ahj_comment=data.get("ahj_comment", violation.violation_text),
                fix_instructions=data.get("fix_instructions", violation.fix_text),
                citations=data.get("citations", violation.code_references),
                rag_passages_used=rag_texts,
            )
        except Exception as e:
            return self._generate_fallback(violation, rag_texts, error=str(e))

    def _generate_fallback(
        self,
        violation: MatchedViolation,
        rag_texts: list[str],
        error: str | None = None,
    ) -> EnrichedViolation:
        """Template-based fallback when Claude API is unavailable."""
        refs = ", ".join(violation.code_references) if violation.code_references else "applicable code"
        ahj_comment = (
            f"[{violation.rule_id}] {violation.discipline} — {violation.violation_text} "
            f"Per {refs}, the design must be revised to comply."
        )
        fix_instructions = (
            f"1. Review {refs}.\n"
            f"2. {violation.fix_text}\n"
            f"3. Resubmit revised drawings for HCAI review."
        )
        return EnrichedViolation(
            violation=violation,
            ahj_comment=ahj_comment,
            fix_instructions=fix_instructions,
            citations=violation.code_references,
            rag_passages_used=rag_texts,
        )
