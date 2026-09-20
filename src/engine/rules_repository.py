"""
RulesRepository — assembles the blueprintIQ rule set and formats it for LLM context.

Usage
-----
repo = RulesRepository()
rules = repo.for_state("TX")           # FGI baseline + TX rules as list[dict]
context = repo.as_llm_context("TX")   # formatted string for Claude system prompt
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import config


class RulesRepository:
    """Loads and serves compliance rules from local JSON files (blueprintIQ local mirror)."""

    def __init__(self) -> None:
        self._cache: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def for_state(self, state_code: str = "CA") -> list[dict]:
        """Return FGI baseline + state-specific rules (deduped by rule id)."""
        code = state_code.upper()
        if code in self._cache:
            return self._cache[code]

        rules: list[dict] = []

        # FGI national baseline
        fgi = self._load(config.FGI_RULES_FILE)
        rules.extend(fgi)

        # State-specific
        if code == "CA":
            rules.extend(self._load(config.HCAI_RULES_FILE))
        else:
            entry = config.STATE_AHJ_MAP.get(code)
            if entry:
                rules.extend(self._load(config.STATES_RULES_DIR / entry["file"]))

        # Deduplicate
        seen: set[str] = set()
        unique: list[dict] = []
        for r in rules:
            rid = r.get("id", "")
            if rid not in seen:
                seen.add(rid)
                unique.append(r)

        self._cache[code] = unique
        return unique

    def all_rules(self) -> list[dict]:
        """Return every rule across all known states (for embedding / search)."""
        combined_path = config.DATA_DIR / "llm" / "blueprintiq_rules.json"
        if combined_path.exists():
            return json.loads(combined_path.read_text())
        # Fallback: build on the fly
        all_codes = ["CA"] + [k for k in config.STATE_AHJ_MAP if k != "CA"]
        seen: set[str] = set()
        out: list[dict] = []
        for code in all_codes:
            for r in self.for_state(code):
                rid = r.get("id", "")
                if rid not in seen:
                    seen.add(rid)
                    out.append(r)
        return out

    def as_llm_context(
        self,
        state_code: str = "CA",
        severity_filter: Optional[list[str]] = None,
        discipline_filter: Optional[str] = None,
        max_rules: int = 60,
    ) -> str:
        """
        Return rules formatted as a compact text block for LLM system prompt injection.

        Parameters
        ----------
        state_code       : 2-letter state code
        severity_filter  : limit to these severities, e.g. ["Critical","High"]
        discipline_filter: substring match on discipline field
        max_rules        : cap total rules returned (to manage token budget)
        """
        rules = self.for_state(state_code)

        if severity_filter:
            rules = [r for r in rules if r.get("severity_override") in severity_filter]
        if discipline_filter:
            df = discipline_filter.lower()
            rules = [r for r in rules if df in r.get("discipline", "").lower()]

        # Critical first, then High, Medium, Low
        _order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        rules = sorted(rules, key=lambda r: _order.get(r.get("severity_override", "Low"), 4))
        rules = rules[:max_rules]

        ahj_name = config.STATE_AHJ_MAP.get(state_code.upper(), {}).get("ahj", "HCAI")
        lines = [
            f"## blueprintIQ Compliance Rules — {state_code} ({ahj_name})",
            f"## {len(rules)} rules  |  FGI 2022 national baseline + {ahj_name} state requirements",
            "",
        ]
        for r in rules:
            occ = ", ".join(r.get("trigger_occupancies") or ["any occupancy"])
            refs = " | ".join(r.get("code_references", []))
            lines += [
                f"### [{r.get('severity_override','?')}] {r['id']} — {r.get('discipline','')}",
                f"**Applies to:** {occ}",
                f"**Violation:** {r.get('violation_template','')}",
                f"**Fix:** {r.get('fix_template','').strip()}",
                f"**Refs:** {refs}",
                "",
            ]

        return "\n".join(lines)

    def stats(self) -> dict:
        """Return a summary dict for logging / API response."""
        combined = config.DATA_DIR / "llm" / "index.json"
        if combined.exists():
            return json.loads(combined.read_text())
        return {"total_rules": len(self.all_rules()), "sources": {}}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except Exception:
            return []
