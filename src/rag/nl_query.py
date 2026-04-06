"""
NaturalLanguageQueryEngine: answer ad-hoc compliance questions in plain English.

Uses the ChromaDB knowledge base for retrieval and Claude for synthesis.
Falls back to a keyword-search summary when the API key is absent.

Example queries:
  "Show me all seismic violations in this project"
  "What waivers have the highest approval rate in California?"
  "Generate a back-check prevention checklist for an occupied hospital OR suite"
  "What are the ASHRAE 170 ACH requirements for an isolation room?"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import config


_SYSTEM_PROMPT = """\
You are an expert HCAI (California Department of Health Care Access and Information) \
plan check engineer with deep knowledge of Title 24, NFPA 99/101, FGI Guidelines, \
and HCAI PINs and CANs.

Answer the user's compliance question accurately and concisely, citing specific \
code sections where relevant.  Format your answer in clear, plain-English prose \
suitable for a design engineer or plan checker to read directly.

If the provided context excerpts are sufficient, base your answer on them.  \
If not, state that clearly rather than inventing requirements.
"""


class NLQueryEngine:
    """Answer plain-English compliance questions using RAG + Claude."""

    def __init__(self, knowledge_base=None) -> None:
        self._kb = knowledge_base  # HCAIKnowledgeBase instance (optional)
        self._client = self._build_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def query(self, question: str, top_k: int = 8) -> "NLQueryResult":
        """
        Answer `question` using regulatory context retrieved from ChromaDB.

        Returns a NLQueryResult with the answer text and source passages.
        """
        passages = self._retrieve_passages(question, top_k)
        context  = self._format_context(passages)

        if self._client:
            answer = self._call_claude(question, context)
        else:
            answer = self._fallback_answer(question, passages)

        return NLQueryResult(question=question, answer=answer, sources=passages)

    async def query_violations(
        self, violations: List[Dict], filter_severity: Optional[str] = None
    ) -> str:
        """
        Summarise a list of violation dicts filtered by severity.

        `violations` should be the JSON-serialisable form of EnrichedViolation objects.
        """
        filtered = violations
        if filter_severity:
            filtered = [
                v for v in violations
                if v.get("severity", "").lower() == filter_severity.lower()
            ]

        if not filtered:
            return f"No violations found" + (f" at severity '{filter_severity}'" if filter_severity else "") + "."

        lines = [f"Found {len(filtered)} violation(s):\n"]
        for v in filtered:
            lines.append(
                f"• [{v.get('severity','?')}] {v.get('rule_id','?')} — "
                f"{v.get('description','')}"
            )
        return "\n".join(lines)

    async def generate_checklist(self, occupancy: str, project_type: str = "new") -> str:
        """
        Generate a back-check prevention checklist for the given occupancy.
        Uses Claude when available; falls back to a structured template.
        """
        question = (
            f"Generate a comprehensive back-check prevention checklist for a "
            f"{'new' if project_type == 'new' else 'renovation'} {occupancy} project "
            f"under California HCAI jurisdiction. "
            f"Include the most commonly cited violations and how to avoid them."
        )
        result = await self.query(question, top_k=10)
        return result.answer

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _retrieve_passages(self, question: str, top_k: int) -> List[Dict]:
        """Query ChromaDB; fall back to rule-file keyword search if KB unavailable."""
        if self._kb:
            try:
                raw = self._kb.query(question, top_k=top_k)
                return [
                    {
                        "id":       r.get("id", ""),
                        "source":   r.get("source", ""),
                        "section":  r.get("section", ""),
                        "text":     r.get("text", r.get("document", "")),
                        "distance": r.get("distance", 0),
                    }
                    for r in (raw if isinstance(raw, list) else [])
                ]
            except Exception:
                pass

        # Keyword fallback: search hcai_rules.json for matching terms
        return self._keyword_search(question, top_k)

    def _keyword_search(self, question: str, top_k: int) -> List[Dict]:
        """Simple keyword search over hcai_rules.json as a fallback."""
        rules_path = Path("data/hcai_rules.json")
        if not rules_path.exists():
            return []

        with open(rules_path) as f:
            rules = json.load(f)

        tokens   = set(question.lower().split())
        scored: List[tuple] = []

        for rule in rules:
            rule_text = " ".join([
                rule.get("description", ""),
                rule.get("violation_template", ""),
                rule.get("discipline", ""),
                " ".join(rule.get("code_references", [])),
            ]).lower()
            score = sum(1 for tok in tokens if tok in rule_text)
            if score:
                scored.append((score, rule))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "id":      r.get("id", ""),
                "source":  "hcai_rules.json",
                "section": r.get("id", ""),
                "text":    f"{r.get('description','')} — {r.get('violation_template','')}",
                "distance": 0,
            }
            for _, r in scored[:top_k]
        ]

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _call_claude(self, question: str, context: str) -> str:
        user_message = f"Context:\n{context}\n\nQuestion: {question}"
        try:
            response = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text.strip()
        except Exception as exc:
            return f"[Claude API error: {exc}]\n\n{self._fallback_answer(question, [])}"

    def _fallback_answer(self, question: str, passages: List[Dict]) -> str:
        if not passages:
            return (
                "No regulatory passages found for that query. "
                "Run `python main.py index-kb` to populate the knowledge base, "
                "or set ANTHROPIC_API_KEY for AI-powered answers."
            )
        lines = [f"Relevant regulatory references for: '{question}'\n"]
        for p in passages[:5]:
            lines.append(f"• [{p.get('source','')} {p.get('section','')}] {p.get('text','')[:200]}…")
        return "\n".join(lines)

    @staticmethod
    def _format_context(passages: List[Dict]) -> str:
        if not passages:
            return "(No regulatory context retrieved.)"
        parts = []
        for p in passages:
            parts.append(
                f"[{p.get('source','')} — {p.get('section','')}]\n{p.get('text','')}"
            )
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _build_client():
        if not config.ANTHROPIC_API_KEY:
            return None
        try:
            import anthropic
            return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        except ImportError:
            return None


class NLQueryResult:
    """Result of a natural-language compliance query."""

    def __init__(self, question: str, answer: str, sources: List[Dict]) -> None:
        self.question = question
        self.answer   = answer
        self.sources  = sources

    def to_dict(self) -> Dict:
        return {
            "question":     self.question,
            "answer":       self.answer,
            "source_count": len(self.sources),
            "sources": [
                {
                    "id":      s.get("id", ""),
                    "source":  s.get("source", ""),
                    "section": s.get("section", ""),
                    "excerpt": s.get("text", "")[:300],
                }
                for s in self.sources
            ],
        }
