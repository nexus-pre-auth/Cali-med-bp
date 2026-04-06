"""
AlertManager: sends webhook (Slack/Teams) and email notifications when model
performance degrades or significant system events occur.

Configuration via environment variables (see config.py):
  ALERT_WEBHOOK_URL  — Slack / Teams incoming webhook URL
  ALERT_EMAIL_*      — SMTP credentials for email digests

Both channels are optional: if unconfigured they silently no-op so the
pipeline never crashes due to a missing notification credential.
"""

from __future__ import annotations

import json
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError


class AlertManager:
    """Send webhook and email alerts for model performance events."""

    # Severity colours for Slack attachments
    _COLOURS = {"critical": "#E53E3E", "warning": "#D69E2E", "info": "#38A169"}

    def __init__(
        self,
        webhook_url: str = "",
        email_from: str = "",
        email_to: str = "",
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_pass: str = "",
    ) -> None:
        self.webhook_url = webhook_url
        self.email_from  = email_from
        self.email_to    = email_to
        self.smtp_host   = smtp_host
        self.smtp_port   = smtp_port
        self.smtp_user   = smtp_user
        self.smtp_pass   = smtp_pass

    # ------------------------------------------------------------------
    # Public alert methods
    # ------------------------------------------------------------------

    async def alert_performance_degradation(self, avg_f1: float, threshold: float) -> None:
        """Fire when the rolling F1 score drops below the threshold."""
        title   = "HCAI Engine — Performance Degradation Alert"
        message = (
            f"Average F1 score has fallen to **{avg_f1:.3f}**, "
            f"below the alert threshold of {threshold:.2f}. "
            "Emergency model retraining has been triggered."
        )
        await self._send("critical", title, message, {"avg_f1": avg_f1, "threshold": threshold})

    async def alert_model_retrained(self, version: str, metrics: Dict) -> None:
        """Fire when a new model version is promoted."""
        title   = f"HCAI Engine — New Model Promoted: {version}"
        message = (
            f"Model **{version}** has been saved after improving F1 by ≥ 0.02.\n"
            f"Waiver F1: {metrics.get('waiver_f1', 'N/A')} | "
            f"Violation F1: {metrics.get('violation_f1', 'N/A')}"
        )
        await self._send("info", title, message, {"version": version, **metrics})

    async def alert_low_feedback_volume(self, count: int, needed: int) -> None:
        """Fire when daily feedback volume falls below the retraining threshold."""
        title   = "HCAI Engine — Low Feedback Volume"
        message = (
            f"Only **{count}** feedback entries received in the last 24 h "
            f"({needed} needed for daily retraining). "
            "Consider onboarding additional AHJ reviewers."
        )
        await self._send("warning", title, message, {"count": count, "needed": needed})

    async def send_daily_digest(self, metrics: Dict) -> None:
        """Send a daily email digest of model performance metrics."""
        if not (self.email_from and self.email_to):
            return

        vd  = metrics.get("violation_detection", {})
        wp  = metrics.get("waiver_prediction", {})
        now = datetime.now().strftime("%Y-%m-%d")

        subject = f"HCAI Compliance Engine — Daily Metrics Digest ({now})"

        html_body = f"""
        <html><body style="font-family:sans-serif;max-width:600px;margin:auto;">
        <h2 style="color:#1a365d;">Daily Performance Digest</h2>
        <p style="color:#718096;">{now}</p>

        <table style="width:100%;border-collapse:collapse;margin-top:16px;">
            <tr style="background:#edf2f7;">
                <th style="padding:10px;text-align:left;">Metric</th>
                <th style="padding:10px;text-align:right;">Value</th>
            </tr>
            <tr><td style="padding:10px;border-bottom:1px solid #e2e8f0;">Violation Detection F1</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:700;">
                    {vd.get('average_f1', 0):.1%}</td></tr>
            <tr><td style="padding:10px;border-bottom:1px solid #e2e8f0;">Precision</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {vd.get('average_precision', 0):.1%}</td></tr>
            <tr><td style="padding:10px;border-bottom:1px solid #e2e8f0;">Recall</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {vd.get('average_recall', 0):.1%}</td></tr>
            <tr><td style="padding:10px;border-bottom:1px solid #e2e8f0;">Total Reviews</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {vd.get('total_reviews', 0)}</td></tr>
            <tr><td style="padding:10px;">Waiver Calibration Error</td>
                <td style="padding:10px;text-align:right;">
                    {wp.get('average_calibration_error', 0):.3f}</td></tr>
        </table>

        <p style="margin-top:24px;font-size:0.85rem;color:#a0aec0;">
            HCAI Autonomous Compliance Engine &nbsp;|&nbsp; Auto-generated digest
        </p>
        </body></html>
        """

        await self._send_email(subject, html_body)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    async def _send(self, level: str, title: str, message: str, data: Dict) -> None:
        """Route alert to all configured channels."""
        await self._send_webhook(level, title, message, data)
        # Email is reserved for digest; individual alerts use webhook only

    async def _send_webhook(self, level: str, title: str, message: str, data: Dict) -> None:
        """POST a Slack-compatible payload to the configured webhook URL."""
        if not self.webhook_url:
            print(f"[AlertManager] {level.upper()} — {title}: {message}")
            return

        colour = self._COLOURS.get(level, "#718096")
        payload = {
            "attachments": [
                {
                    "color": colour,
                    "title": title,
                    "text":  message,
                    "fields": [
                        {"title": k, "value": str(v), "short": True}
                        for k, v in data.items()
                    ],
                    "footer": "HCAI Compliance Engine",
                    "ts": int(datetime.now().timestamp()),
                }
            ]
        }

        body = json.dumps(payload).encode()
        req  = Request(self.webhook_url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 204):
                    print(f"[AlertManager] Webhook returned HTTP {resp.status}")
        except URLError as exc:
            print(f"[AlertManager] Webhook delivery failed: {exc}")

    async def _send_email(self, subject: str, html_body: str) -> None:
        """Send an HTML email via SMTP."""
        if not (self.email_from and self.email_to and self.smtp_user and self.smtp_pass):
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self.email_from
        msg["To"]      = self.email_to
        msg.attach(MIMEText(html_body, "html"))

        ctx = ssl.create_default_context()
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.email_from, self.email_to, msg.as_string())
        except Exception as exc:
            print(f"[AlertManager] Email delivery failed: {exc}")
