"""
ContinuousLearningPipeline: APScheduler-based automation that:

  - Runs incremental retraining daily at 02:00 (if ≥ 25 new feedback records)
  - Runs full retraining every Sunday at 03:00
  - Aggregates metrics hourly and fires an emergency retrain if F1 < 0.70
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    HAS_SCHEDULER = True
except ImportError:
    HAS_SCHEDULER = False

from src.feedback.processor import FeedbackProcessor
from src.ml.alerting import AlertManager
from src.ml.trainer import ModelTrainer


class ContinuousLearningPipeline:
    """Automated, scheduler-driven continuous learning pipeline."""

    DAILY_FEEDBACK_THRESHOLD = 25   # Minimum new records to trigger daily retrain
    F1_ALERT_THRESHOLD       = 0.70 # Emergency retrain if avg F1 falls below this

    def __init__(self) -> None:
        self.feedback_processor = FeedbackProcessor()
        self.model_trainer      = ModelTrainer()
        self.alert_manager      = AlertManager(
            webhook_url = os.getenv("ALERT_WEBHOOK_URL", ""),
            email_from  = os.getenv("ALERT_EMAIL_FROM", ""),
            email_to    = os.getenv("ALERT_EMAIL_TO", ""),
            smtp_host   = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com"),
            smtp_port   = int(os.getenv("ALERT_SMTP_PORT", "587")),
            smtp_user   = os.getenv("ALERT_SMTP_USER", ""),
            smtp_pass   = os.getenv("ALERT_SMTP_PASS", ""),
        )

        if HAS_SCHEDULER:
            self.scheduler = AsyncIOScheduler()
        else:
            self.scheduler = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register all scheduled jobs and start the scheduler."""
        if not HAS_SCHEDULER:
            print("[ContinuousLearning] apscheduler not installed; pipeline disabled.")
            return

        self.scheduler.add_job(
            self.daily_retraining,
            "cron",
            hour=2,
            minute=0,
            id="daily_retraining",
        )
        self.scheduler.add_job(
            self.weekly_deep_retraining,
            "cron",
            day_of_week="sun",
            hour=3,
            minute=0,
            id="weekly_retraining",
        )
        self.scheduler.add_job(
            self.aggregate_metrics,
            "interval",
            hours=1,
            id="metrics_aggregation",
        )
        self.scheduler.add_job(
            self.send_daily_digest,
            "cron",
            hour=7,
            minute=0,
            id="daily_email_digest",
        )

        self.scheduler.start()
        print("[ContinuousLearning] Pipeline started.")

    def stop(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()
            print("[ContinuousLearning] Pipeline stopped.")

    # ------------------------------------------------------------------
    # Scheduled jobs
    # ------------------------------------------------------------------

    async def daily_retraining(self) -> None:
        """Incremental retrain if enough fresh feedback has arrived today."""
        print(f"[{datetime.now().isoformat()}] Daily retraining check...")
        new_count = await self._count_new_feedback(days=1)

        if new_count >= self.DAILY_FEEDBACK_THRESHOLD:
            await self.model_trainer.trigger_retraining("daily_schedule")
        else:
            print(
                f"[ContinuousLearning] Skipping daily retrain: "
                f"{new_count}/{self.DAILY_FEEDBACK_THRESHOLD} required."
            )
            if new_count < self.DAILY_FEEDBACK_THRESHOLD // 2:
                await self.alert_manager.alert_low_feedback_volume(
                    new_count, self.DAILY_FEEDBACK_THRESHOLD
                )

    async def weekly_deep_retraining(self) -> None:
        """Full retrain over all available data every Sunday."""
        print(f"[{datetime.now().isoformat()}] Weekly deep retraining...")
        await self.model_trainer.trigger_retraining("weekly_schedule")
        await self._ab_test_models()

    async def aggregate_metrics(self) -> None:
        """Hourly metric roll-up; triggers emergency retrain on degradation."""
        metrics = await self.feedback_processor.get_metrics(days=30)
        avg_f1  = metrics["violation_detection"]["average_f1"]

        if avg_f1 < self.F1_ALERT_THRESHOLD and avg_f1 > 0:
            print(f"[ContinuousLearning] ALERT — avg F1 {avg_f1:.3f} below threshold.")
            await self.alert_manager.alert_performance_degradation(avg_f1, self.F1_ALERT_THRESHOLD)
            await self._trigger_emergency_retraining()

        await self._save_to_monitoring(metrics)

    async def send_daily_digest(self) -> None:
        """Send the daily email performance digest (called by scheduler)."""
        metrics = await self.feedback_processor.get_metrics(days=1)
        await self.alert_manager.send_daily_digest(metrics)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _count_new_feedback(self, days: int) -> int:
        cutoff   = datetime.now() - timedelta(days=days)
        feedback_dir = Path("data/feedback")
        if not feedback_dir.exists():
            return 0
        return sum(
            1 for fp in feedback_dir.glob("*.json")
            if datetime.fromtimestamp(fp.stat().st_ctime) > cutoff
        )

    async def _trigger_emergency_retraining(self) -> None:
        print("[ContinuousLearning] Emergency retraining triggered.")
        await self.model_trainer.trigger_retraining("emergency_degradation")

    async def _ab_test_models(self) -> None:
        """
        Placeholder for A/B testing between model versions.
        Implement by routing a holdout slice of traffic to the previous
        model version and comparing F1 scores before promoting the new one.
        """
        pass

    async def _save_to_monitoring(self, metrics: dict) -> None:
        """
        Placeholder for exporting to an external monitoring system
        (Prometheus push-gateway, CloudWatch, Datadog, etc.).
        """
        pass
