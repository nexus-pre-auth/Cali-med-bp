"""
Webhook Notifier — sends compliance alerts and daily digests via HTTP.

Supports:
  - Immediate Critical/High alerts (per review)
  - Daily summary digest
  - Slack-compatible payloads
  - Generic JSON webhook (n8n, Make, Zapier, etc.)

Configure via environment variables:
  WEBHOOK_URL        — generic JSON endpoint
  SLACK_WEBHOOK_URL  — Slack incoming webhook URL
  NOTIFY_MIN_SEVERITY — minimum severity to trigger immediate alert (default: Critical)
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional

from src.engine.severity_scorer import Severity
from src.rag.generator import EnrichedViolation
from src.monitoring.logger import get_logger
from src.utils.api_utils import with_retry

log = get_logger(__name__)

_SEVERITY_EMOJI = {
    "Critical": "🔴",
    "High":     "🟠",
    "Medium":   "🟡",
    "Low":      "🟢",
}


def _post_json(url: str, payload: dict, timeout: int = 10) -> bool:
    """POST JSON payload to URL. Returns True on 2xx."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.URLError as e:
        log.warning("Webhook POST failed: %s", e)
        return False


class WebhookNotifier:
    """
    Sends notifications about compliance review results.

    Parameters
    ----------
    webhook_url       : Generic JSON webhook endpoint
    slack_webhook_url : Slack incoming webhook URL
    min_severity      : Minimum Severity to trigger an immediate alert
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        min_severity: Severity = Severity.CRITICAL,
    ) -> None:
        self._webhook_url       = webhook_url       or os.getenv("WEBHOOK_URL")
        self._slack_webhook_url = slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self._min_severity      = min_severity

        min_env = os.getenv("NOTIFY_MIN_SEVERITY", "").strip()
        if min_env and min_env in [s.value for s in Severity]:
            self._min_severity = Severity(min_env)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_review_alert(
        self,
        enriched: list[EnrichedViolation],
        project_name: str,
        report_paths: Optional[dict] = None,
    ) -> None:
        """
        Send an immediate alert if violations at or above min_severity were found.
        """
        critical_evs = [
            ev for ev in enriched
            if ev.violation.severity.order <= self._min_severity.order
        ]
        if not critical_evs:
            return

        payload = self._build_alert_payload(critical_evs, project_name, report_paths)
        self._dispatch(payload, event="critical_alert")

    def send_daily_summary(
        self,
        sessions: list[dict],
        date: Optional[str] = None,
    ) -> None:
        """
        Send a daily digest summarising all completed reviews.

        Parameters
        ----------
        sessions : list of metric summary dicts from SessionMetrics.summary()
        date     : ISO date string (defaults to today)
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        total_violations = sum(s.get("violations_found", 0) for s in sessions)
        total_critical   = sum(s.get("violations_by_severity", {}).get("Critical", 0) for s in sessions)

        payload = {
            "event":           "daily_summary",
            "date":            date,
            "sessions_run":    len(sessions),
            "total_violations": total_violations,
            "total_critical":  total_critical,
            "sessions":        sessions,
        }
        self._dispatch(payload, event="daily_summary")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_alert_payload(
        self,
        evs: list[EnrichedViolation],
        project_name: str,
        report_paths: Optional[dict],
    ) -> dict:
        return {
            "event":        "compliance_alert",
            "project":      project_name,
            "timestamp":    datetime.utcnow().isoformat() + "Z",
            "alert_count":  len(evs),
            "violations": [
                {
                    "rule_id":    ev.violation.rule_id,
                    "severity":   ev.violation.severity.value,
                    "discipline": ev.violation.discipline,
                    "summary":    ev.ahj_comment[:200] + "…" if len(ev.ahj_comment) > 200 else ev.ahj_comment,
                }
                for ev in evs
            ],
            "report_paths": {k: str(v) for k, v in (report_paths or {}).items()},
        }

    def _build_slack_payload(self, payload: dict) -> dict:
        event = payload.get("event", "")

        if event == "compliance_alert":
            violations = payload.get("violations", [])
            blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"🚨 HCAI Compliance Alert — {payload['project']}"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{payload['alert_count']} high-priority violation(s) detected*",
                    },
                },
            ]
            for v in violations[:5]:  # Cap at 5 to avoid message size limits
                emoji = _SEVERITY_EMOJI.get(v["severity"], "⚪")
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{emoji} *[{v['rule_id']}] {v['discipline']}* ({v['severity']})\n{v['summary']}",
                    },
                })
            if len(violations) > 5:
                blocks.append({
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"…and {len(violations) - 5} more violations"}],
                })
            return {"blocks": blocks}

        if event == "daily_summary":
            return {
                "text": (
                    f"📊 *HCAI Daily Summary — {payload['date']}*\n"
                    f"Sessions: {payload['sessions_run']}  |  "
                    f"Total violations: {payload['total_violations']}  |  "
                    f"Critical: {payload['total_critical']}"
                )
            }

        return {"text": json.dumps(payload)}

    @with_retry(max_attempts=3, base_delay=2.0, exceptions=(urllib.error.URLError,))
    def _dispatch(self, payload: dict, event: str = "") -> None:
        sent = False

        if self._webhook_url:
            ok = _post_json(self._webhook_url, payload)
            log.info("Generic webhook %s → %s", event, "OK" if ok else "FAILED")
            sent = True

        if self._slack_webhook_url:
            slack_payload = self._build_slack_payload(payload)
            ok = _post_json(self._slack_webhook_url, slack_payload)
            log.info("Slack webhook %s → %s", event, "OK" if ok else "FAILED")
            sent = True

        if not sent:
            log.debug("No webhook URLs configured — skipping notification for event '%s'", event)
