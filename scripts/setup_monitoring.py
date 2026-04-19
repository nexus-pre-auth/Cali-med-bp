#!/usr/bin/env python3
"""
setup_monitoring.py — Interactive setup wizard for the HCAI monitoring stack.

Guides the operator through:
  1. Webhook URL (Slack / Teams / generic)
  2. Email digest (SMTP)
  3. Alert thresholds
  4. Verifying connectivity

Writes validated values into a .env file (or updates an existing one).

Usage:
    python scripts/setup_monitoring.py
    python scripts/setup_monitoring.py --check   # test existing config only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value  = input(f"{prompt}{suffix}: ").strip()
    return value or default


def _ask_bool(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    raw    = input(f"{prompt}{suffix}: ").strip().lower()
    if not raw:
        return default
    return raw.startswith("y")


def _test_webhook(url: str) -> bool:
    """Send a test Slack-compatible message to verify the webhook works."""
    payload = json.dumps({"text": "HCAI Engine monitoring test — OK"}).encode()
    req     = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except (URLError, Exception) as exc:
        print(f"  Webhook test failed: {exc}")
        return False


def _update_env_file(env_path: Path, updates: dict) -> None:
    """Merge `updates` into an existing .env file (or create it)."""
    existing: dict = {}

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    existing.update(updates)

    lines = [f"{k}={v}" for k, v in existing.items()]
    env_path.write_text("\n".join(lines) + "\n")
    print(f"\n  .env written to {env_path}")


def _check_existing_config() -> None:
    """Validate the current .env monitoring configuration."""
    from dotenv import load_dotenv
    load_dotenv()

    print("\nChecking current monitoring configuration...\n")

    webhook = os.getenv("ALERT_WEBHOOK_URL", "")
    email   = os.getenv("ALERT_EMAIL_TO", "")

    if not webhook and not email:
        print("  No alerting channels configured.")
        print("  Run: python scripts/setup_monitoring.py")
        sys.exit(1)

    if webhook:
        print(f"  Webhook URL : {webhook[:40]}...")
        ok = _test_webhook(webhook)
        print(f"  Webhook test: {'OK' if ok else 'FAILED'}")
    else:
        print("  Webhook     : not configured")

    if email:
        print(f"  Email to    : {email}")
        print("  Email test  : skipped (would send real email)")
    else:
        print("  Email       : not configured")

    threshold = os.getenv("F1_ALERT_THRESHOLD", "0.70")
    print(f"  F1 threshold: {threshold}")
    print()


# ---------------------------------------------------------------------------
# Main setup wizard
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="HCAI monitoring setup wizard")
    parser.add_argument("--check", action="store_true", help="Test existing configuration only")
    args = parser.parse_args()

    if args.check:
        _check_existing_config()
        return

    env_path = Path(__file__).parent.parent / ".env"

    print("\n" + "=" * 60)
    print("  HCAI Compliance Engine — Monitoring Setup")
    print("=" * 60)
    print()

    updates: dict = {}

    # ── Webhook ──────────────────────────────────────────────────────
    print("1. WEBHOOK ALERTS (Slack / Microsoft Teams / generic HTTP)")
    print("   Slack:  Settings → Integrations → Incoming Webhooks")
    print("   Teams:  Channel → Connectors → Incoming Webhook")
    print()

    if _ask_bool("Configure webhook alerts?", default=True):
        webhook = _ask("   Webhook URL")
        if webhook:
            print("   Testing webhook...", end=" ", flush=True)
            if _test_webhook(webhook):
                print("OK")
                updates["ALERT_WEBHOOK_URL"] = webhook
            else:
                if _ask_bool("   Test failed. Save anyway?", default=False):
                    updates["ALERT_WEBHOOK_URL"] = webhook

    # ── Email ────────────────────────────────────────────────────────
    print("\n2. EMAIL DIGEST (daily summary at 07:00)")
    if _ask_bool("Configure email digest?", default=False):
        updates["ALERT_EMAIL_FROM"]  = _ask("   From address")
        updates["ALERT_EMAIL_TO"]    = _ask("   To address(es)  (comma-separated)")
        updates["ALERT_SMTP_HOST"]   = _ask("   SMTP host",  default="smtp.gmail.com")
        updates["ALERT_SMTP_PORT"]   = _ask("   SMTP port",  default="587")
        updates["ALERT_SMTP_USER"]   = _ask("   SMTP username")
        updates["ALERT_SMTP_PASS"]   = _ask("   SMTP password (app password for Gmail)")
        print()
        print("   Note: for Gmail, generate an App Password at:")
        print("   https://myaccount.google.com/apppasswords")

    # ── Thresholds ───────────────────────────────────────────────────
    print("\n3. ALERT THRESHOLDS")
    f1_thresh = _ask("   F1 alert threshold", default="0.70")
    try:
        float(f1_thresh)
        updates["F1_ALERT_THRESHOLD"] = f1_thresh
    except ValueError:
        print("   Invalid value; keeping default 0.70")

    # ── Batch worker count ───────────────────────────────────────────
    print("\n4. BATCH PROCESSING")
    workers = _ask("   Max parallel workers for batch reviews", default="4")
    updates["BATCH_MAX_WORKERS"] = workers

    # ── Write ────────────────────────────────────────────────────────
    if updates:
        _update_env_file(env_path, updates)
        print()
        print("Configuration saved. To apply immediately:")
        print("  source .env   # bash")
        print("  # or restart the server: python main.py serve")
    else:
        print("\nNo changes made.")

    print()


if __name__ == "__main__":
    main()
