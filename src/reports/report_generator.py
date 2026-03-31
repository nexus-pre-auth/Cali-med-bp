"""
Report Generator — produces HCAI-style plan review reports.

Outputs:
  - JSON  : machine-readable violation list
  - HTML  : formatted report with severity badges
  - Text  : plain-text AHJ comment sheet
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import config
from src.engine.severity_scorer import Severity
from src.parser.condition_extractor import ProjectConditions
from src.rag.generator import EnrichedViolation

try:
    import jinja2 as _jinja2  # noqa: F401
    HAS_JINJA = True
except ImportError:
    HAS_JINJA = False


# ---------------------------------------------------------------------------
# Plain-text renderer
# ---------------------------------------------------------------------------

def _severity_bar(severity: str) -> str:
    bars = {
        "Critical": "████████ CRITICAL",
        "High":     "██████   HIGH",
        "Medium":   "████     MEDIUM",
        "Low":      "██       LOW",
    }
    return bars.get(severity, severity)


def render_text_report(
    enriched: list[EnrichedViolation],
    conditions: ProjectConditions,
    project_name: str = "Healthcare Project",
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "=" * 72,
        "  HCAI PLAN REVIEW — COMPLIANCE REPORT",
        f"  Project : {project_name}",
        f"  Date    : {now}",
        f"  Facility: {conditions.occupancy_type or 'N/A'}",
        f"  County  : {conditions.county or 'N/A'}",
        "=" * 72,
        "",
    ]

    # Summary
    counts = {s.value: 0 for s in Severity}
    for ev in enriched:
        counts[ev.violation.severity.value] += 1

    lines += [
        "SUMMARY",
        "-------",
        f"  Total Violations : {len(enriched)}",
        f"  Critical         : {counts['Critical']}",
        f"  High             : {counts['High']}",
        f"  Medium           : {counts['Medium']}",
        f"  Low              : {counts['Low']}",
        "",
        "VIOLATIONS",
        "----------",
    ]

    for i, ev in enumerate(enriched, 1):
        v = ev.violation
        lines += [
            "",
            f"[{i}] {_severity_bar(v.severity.value)}",
            f"Rule     : {v.rule_id}",
            f"Discipline: {v.discipline}",
            f"Trigger  : {v.trigger_condition}",
            "",
            "AHJ COMMENT:",
            ev.ahj_comment,
            "",
            "FIX INSTRUCTIONS:",
            ev.fix_instructions,
            "",
            "CITATIONS:",
            "\n".join(f"  - {c}" for c in ev.citations),
            "",
            "-" * 72,
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------

def render_json_report(
    enriched: list[EnrichedViolation],
    conditions: ProjectConditions,
    project_name: str = "Healthcare Project",
) -> str:
    output = {
        "project": project_name,
        "generated_at": datetime.now().isoformat(),
        "facility_type": conditions.occupancy_type,
        "county": conditions.county,
        "summary": {
            "total": len(enriched),
            "by_severity": {s.value: sum(1 for ev in enriched if ev.violation.severity.value == s.value) for s in Severity},
        },
        "violations": [
            {
                "rule_id": ev.violation.rule_id,
                "discipline": ev.violation.discipline,
                "severity": ev.violation.severity.value,
                "trigger_condition": ev.violation.trigger_condition,
                "ahj_comment": ev.ahj_comment,
                "fix_instructions": ev.fix_instructions,
                "citations": ev.citations,
            }
            for ev in enriched
        ],
    }
    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HCAI Compliance Report — {{ project_name }}</title>
<style>
  :root {
    --critical: #E53E3E; --high: #DD6B20; --medium: #D69E2E; --low: #38A169;
    --bg: #F7FAFC; --card: #FFFFFF; --border: #E2E8F0; --text: #2D3748;
  }
  body { font-family: 'Segoe UI', Arial, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 24px; }
  .header { background: #1A365D; color: white; padding: 24px 32px; border-radius: 8px; margin-bottom: 24px; }
  .header h1 { margin: 0 0 4px 0; font-size: 1.6em; }
  .header p  { margin: 2px 0; opacity: 0.85; font-size: 0.9em; }
  .summary { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  .pill { padding: 12px 24px; border-radius: 8px; color: white; font-weight: bold; font-size: 1.1em; }
  .pill-critical { background: var(--critical); }
  .pill-high     { background: var(--high); }
  .pill-medium   { background: var(--medium); }
  .pill-low      { background: var(--low); }
  .violation { background: var(--card); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 16px; overflow: hidden; }
  .violation-header { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border); }
  .badge { padding: 4px 12px; border-radius: 999px; color: white; font-size: 0.8em; font-weight: bold; }
  .badge-Critical { background: var(--critical); }
  .badge-High     { background: var(--high); }
  .badge-Medium   { background: var(--medium); }
  .badge-Low      { background: var(--low); }
  .rule-id { font-family: monospace; color: #718096; font-size: 0.85em; }
  .discipline { font-weight: 600; color: var(--text); }
  .violation-body { padding: 16px; }
  .section-label { font-size: 0.75em; font-weight: bold; text-transform: uppercase; color: #718096; margin-bottom: 4px; }
  .ahj-comment { background: #EBF8FF; border-left: 4px solid #3182CE; padding: 10px 14px; border-radius: 0 4px 4px 0; margin-bottom: 12px; }
  .fix-box { background: #F0FFF4; border-left: 4px solid var(--low); padding: 10px 14px; border-radius: 0 4px 4px 0; white-space: pre-line; margin-bottom: 12px; }
  .citations { font-size: 0.85em; color: #4A5568; }
  .citations ul { margin: 4px 0; padding-left: 20px; }
  footer { text-align: center; margin-top: 32px; font-size: 0.8em; color: #A0AEC0; }
</style>
</head>
<body>

<div class="header">
  <h1>HCAI Plan Review — Compliance Report</h1>
  <p>Project: <strong>{{ project_name }}</strong></p>
  <p>Facility: {{ conditions.occupancy_type or "N/A" }} &nbsp;|&nbsp; County: {{ conditions.county or "N/A" }}</p>
  <p>Generated: {{ generated_at }}</p>
</div>

<div class="summary">
  <div class="pill pill-critical">Critical: {{ counts.Critical }}</div>
  <div class="pill pill-high">High: {{ counts.High }}</div>
  <div class="pill pill-medium">Medium: {{ counts.Medium }}</div>
  <div class="pill pill-low">Low: {{ counts.Low }}</div>
  <div class="pill" style="background:#4A5568;">Total: {{ total }}</div>
</div>

{% for ev in enriched %}
<div class="violation">
  <div class="violation-header">
    <span class="badge badge-{{ ev.violation.severity.value }}">{{ ev.violation.severity.value }}</span>
    <span class="rule-id">{{ ev.violation.rule_id }}</span>
    <span class="discipline">{{ ev.violation.discipline }}</span>
    <span style="margin-left:auto; font-size:0.85em; color:#718096;">{{ ev.violation.trigger_condition }}</span>
  </div>
  <div class="violation-body">
    <div class="section-label">AHJ Plan Review Comment</div>
    <div class="ahj-comment">{{ ev.ahj_comment }}</div>

    <div class="section-label">Step-by-Step Compliance Fix</div>
    <div class="fix-box">{{ ev.fix_instructions }}</div>

    <div class="citations">
      <div class="section-label">Code Citations</div>
      <ul>{% for c in ev.citations %}<li>{{ c }}</li>{% endfor %}</ul>
    </div>
  </div>
</div>
{% endfor %}

<footer>
  Autonomous HCAI Compliance Engine &mdash; {{ generated_at }}<br>
  This report is generated for plan review purposes. Always verify with the current adopted edition of Title 24 CBC and HCAI policy documents.
</footer>
</body>
</html>
"""


def render_html_report(
    enriched: list[EnrichedViolation],
    conditions: ProjectConditions,
    project_name: str = "Healthcare Project",
) -> str:
    if not HAS_JINJA:
        # Minimal fallback
        return f"<html><body><pre>{render_text_report(enriched, conditions, project_name)}</pre></body></html>"

    from jinja2 import Environment
    env = Environment(autoescape=False)
    template = env.from_string(_HTML_TEMPLATE)

    counts = {s.value: sum(1 for ev in enriched if ev.violation.severity.value == s.value) for s in Severity}

    return template.render(
        project_name=project_name,
        conditions=conditions,
        enriched=enriched,
        counts=counts,
        total=len(enriched),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------

class ReportWriter:
    def __init__(self, output_dir: str | Path | None = None) -> None:
        self._out = Path(output_dir or config.OUTPUT_DIR)
        self._out.mkdir(parents=True, exist_ok=True)

    def write_all(
        self,
        enriched: list[EnrichedViolation],
        conditions: ProjectConditions,
        project_name: str = "Healthcare Project",
        stem: str = "hcai_report",
        formats: str = "all",
    ) -> dict[str, Path]:
        paths = {}
        want_all = formats == "all"

        if want_all or formats == "text":
            txt_path = self._out / f"{stem}.txt"
            txt_path.write_text(render_text_report(enriched, conditions, project_name))
            paths["text"] = txt_path

        if want_all or formats == "json":
            json_path = self._out / f"{stem}.json"
            json_path.write_text(render_json_report(enriched, conditions, project_name))
            paths["json"] = json_path

        if want_all or formats == "html":
            html_path = self._out / f"{stem}.html"
            html_path.write_text(render_html_report(enriched, conditions, project_name))
            paths["html"] = html_path

        return paths
