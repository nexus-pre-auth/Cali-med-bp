#!/usr/bin/env python3
"""
weekly_retrain.py — Standalone retraining script for cron / systemd timer use.

Intended for deployments that don't run the FastAPI server continuously.
Add to crontab with:

    # Every Sunday at 03:00
    0 3 * * 0 /usr/bin/python3 /app/scripts/weekly_retrain.py >> /var/log/hcai_retrain.log 2>&1

The script exits 0 on success / skipped, 1 on error.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on the path when called from cron
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


async def _retrain() -> int:
    """Run the full retraining pipeline; return exit code."""
    from src.ml.trainer   import ModelTrainer
    from src.ml.alerting  import AlertManager
    import os

    print(f"[{datetime.now().isoformat()}] HCAI weekly retraining starting...")

    trainer = ModelTrainer(model_dir=PROJECT_ROOT / "data" / "models")
    alerter = AlertManager(
        webhook_url = os.getenv("ALERT_WEBHOOK_URL", ""),
        email_from  = os.getenv("ALERT_EMAIL_FROM", ""),
        email_to    = os.getenv("ALERT_EMAIL_TO", ""),
        smtp_host   = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com"),
        smtp_port   = int(os.getenv("ALERT_SMTP_PORT", "587")),
        smtp_user   = os.getenv("ALERT_SMTP_USER", ""),
        smtp_pass   = os.getenv("ALERT_SMTP_PASS", ""),
    )

    prev_version = trainer.current_model_version

    try:
        await trainer.trigger_retraining("weekly_cron")
    except Exception as exc:
        print(f"[ERROR] Retraining failed: {exc}")
        return 1

    new_version = trainer.current_model_version

    if new_version != prev_version:
        print(f"[OK] New model promoted: {prev_version} → {new_version}")
        # Load metrics for the alert
        registry_path = PROJECT_ROOT / "data" / "models" / "model_metrics.json"
        metrics: dict = {}
        if registry_path.exists():
            with open(registry_path) as f:
                history = json.load(f)
            if history:
                metrics = history[-1]
        await alerter.alert_model_retrained(new_version, metrics)
    else:
        print(f"[OK] No improvement — current model retained ({prev_version})")

    print(f"[{datetime.now().isoformat()}] Weekly retraining complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_retrain()))
