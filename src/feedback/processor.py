"""
FeedbackProcessor: stores AHJ feedback to disk and computes running accuracy
metrics used by the ML training pipeline.

Storage strategy: JSON files under data/feedback/ (no external DB required).
Metrics are aggregated into data/metrics/*.json for the trainer to consume.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.feedback.models import AHJFeedback, FeedbackType


class FeedbackProcessor:
    def __init__(
        self,
        storage_path: Path = Path("data/feedback"),
        metrics_path: Path = Path("data/metrics"),
    ):
        self.storage_path = storage_path
        self.metrics_path = metrics_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.metrics_path.mkdir(parents=True, exist_ok=True)
        self.batch_threshold = 50       # Retrain after N feedback entries in window
        self.batch_window_hours = 24

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    async def store_feedback(self, feedback: AHJFeedback) -> AHJFeedback:
        """Persist feedback as a JSON file."""
        dest = self.storage_path / f"{feedback.feedback_id}.json"
        with open(dest, "w") as f:
            json.dump(feedback.model_dump(mode="json"), f, default=str, indent=2)
        return feedback

    # ------------------------------------------------------------------
    # Processing dispatch
    # ------------------------------------------------------------------

    async def process_feedback_batch(self, feedback: AHJFeedback) -> None:
        """Route feedback to the appropriate metric-update handler."""
        if feedback.feedback_type == FeedbackType.VIOLATION_DETECTION:
            await self._update_violation_metrics(feedback)
        elif feedback.feedback_type == FeedbackType.WAIVER_PREDICTION:
            await self._update_waiver_metrics(feedback)
        elif feedback.feedback_type == FeedbackType.AI_COMMENT_QUALITY:
            await self._update_comment_metrics(feedback)
        await self._log_to_audit(feedback)

    async def process_batch(self, feedback_ids: List[str]) -> None:
        """Process a list of already-stored feedback IDs."""
        for fid in feedback_ids:
            path = self.storage_path / f"{fid}.json"
            if not path.exists():
                continue
            with open(path) as f:
                data = json.load(f)
            fb = AHJFeedback.model_validate(data)
            await self.process_feedback_batch(fb)

    # ------------------------------------------------------------------
    # Metric updaters
    # ------------------------------------------------------------------

    async def _update_violation_metrics(self, feedback: AHJFeedback) -> None:
        """Compute precision / recall / F1 for one feedback entry and append."""
        tp = len([
            v for v in feedback.detected_violations
            if v in feedback.ahj_actual_violations
        ])
        fp = len(feedback.false_positives)
        fn = len(feedback.false_negatives)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = (2 * precision * recall / (precision + recall)
                     if (precision + recall) > 0 else 0.0)

        record = {
            "timestamp": datetime.now().isoformat(),
            "job_id": feedback.job_id,
            "ahj_name": feedback.ahj_name,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
        }
        self._append_metric("violation_accuracy.json", record)
        await self._update_rule_accuracy(feedback)

    async def _update_waiver_metrics(self, feedback: AHJFeedback) -> None:
        """Record predicted vs actual waiver outcome and calibration error."""
        record: Dict = {
            "timestamp": datetime.now().isoformat(),
            "job_id": feedback.job_id,
            "predicted_probability": feedback.waiver_predicted_probability,
            "actual_outcome": feedback.waiver_actual_outcome,
            "calibration_error": None,
        }
        if feedback.waiver_predicted_probability is not None and feedback.waiver_actual_outcome:
            actual = 1.0 if feedback.waiver_actual_outcome == "approved" else 0.0
            record["calibration_error"] = abs(feedback.waiver_predicted_probability - actual)
        self._append_metric("waiver_accuracy.json", record)

    async def _update_comment_metrics(self, feedback: AHJFeedback) -> None:
        """Record AI comment quality ratings."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "job_id": feedback.job_id,
            "ahj_name": feedback.ahj_name,
            "rating": feedback.ai_comment_rating,
            "used_as_is": feedback.ai_comment_used_as_is,
            "time_saved_minutes": feedback.time_saved_minutes,
        }
        self._append_metric("comment_quality.json", record)

    async def _update_rule_accuracy(self, feedback: AHJFeedback) -> None:
        """Accumulate per-rule TP/FP/FN counts and recompute accuracy."""
        rule_path = self.metrics_path / "rule_accuracy.json"
        rule_accuracy: Dict = {}
        if rule_path.exists():
            with open(rule_path) as f:
                rule_accuracy = json.load(f)

        _default = lambda: {"true_positives": 0, "false_positives": 0, "false_negatives": 0, "total": 0}
        fp_set = set(feedback.false_positives)

        # True positives: detected rules confirmed by the AHJ (not in false_positives)
        for v in feedback.detected_violations:
            rule_id = v.get("rule_id") if isinstance(v, dict) else None
            if rule_id and rule_id not in fp_set:
                stats = rule_accuracy.setdefault(rule_id, _default())
                stats.setdefault("true_positives", 0)
                stats["true_positives"] += 1
                stats["total"] += 1

        # False positives: rules we flagged that the AHJ did not cite
        for rule_id in feedback.false_positives:
            stats = rule_accuracy.setdefault(rule_id, _default())
            stats.setdefault("true_positives", 0)
            stats["false_positives"] += 1
            stats["total"] += 1

        # False negatives: rules the AHJ cited that we missed
        for rule_id in feedback.false_negatives:
            stats = rule_accuracy.setdefault(rule_id, _default())
            stats.setdefault("true_positives", 0)
            stats["false_negatives"] += 1
            stats["total"] += 1

        # Recompute accuracy: tp / (tp + fp + fn)
        for stats in rule_accuracy.values():
            tp = stats.get("true_positives", 0)
            stats["accuracy"] = tp / stats["total"] if stats["total"] > 0 else 1.0

        with open(rule_path, "w") as f:
            json.dump(rule_accuracy, f, indent=2)

    async def _log_to_audit(self, feedback: AHJFeedback) -> None:
        """Append a lightweight audit record."""
        audit_path = self.metrics_path / "audit_log.json"
        entries: List[Dict] = []
        if audit_path.exists():
            with open(audit_path) as f:
                entries = json.load(f)
        entries.append({
            "feedback_id": feedback.feedback_id,
            "job_id": feedback.job_id,
            "ahj_name": feedback.ahj_name,
            "feedback_type": feedback.feedback_type.value,
            "created_at": feedback.created_at.isoformat(),
        })
        with open(audit_path, "w") as f:
            json.dump(entries, f, indent=2)

    # ------------------------------------------------------------------
    # Retraining gate
    # ------------------------------------------------------------------

    async def should_retrain(self) -> bool:
        """Return True when recent feedback count meets the batch threshold."""
        now = datetime.now()
        cutoff = now - timedelta(hours=self.batch_window_hours)
        count = sum(
            1 for fp in self.storage_path.glob("*.json")
            if datetime.fromtimestamp(fp.stat().st_ctime) > cutoff
        )
        return count >= self.batch_threshold

    # ------------------------------------------------------------------
    # Metrics API
    # ------------------------------------------------------------------

    async def get_metrics(self, days: int = 30, ahj_name: Optional[str] = None) -> Dict:
        """Return aggregated metrics for the requested look-back window."""
        cutoff = datetime.now() - timedelta(days=days)

        violation_metrics = self._load_metric_file("violation_accuracy.json")
        waiver_metrics    = self._load_metric_file("waiver_accuracy.json")

        filtered_v = [
            m for m in violation_metrics
            if datetime.fromisoformat(m["timestamp"]) > cutoff
            and (ahj_name is None or m.get("ahj_name") == ahj_name)
        ]

        avg = lambda key: (
            sum(m[key] for m in filtered_v) / len(filtered_v) if filtered_v else 0.0
        )

        filtered_w = [
            m for m in waiver_metrics
            if datetime.fromisoformat(m["timestamp"]) > cutoff
            and (ahj_name is None or m.get("ahj_name") == ahj_name)
        ]
        waiver_cal = [m["calibration_error"] for m in filtered_w if m.get("calibration_error") is not None]

        return {
            "period_days": days,
            "violation_detection": {
                "average_precision": round(avg("precision"), 3),
                "average_recall":    round(avg("recall"), 3),
                "average_f1":        round(avg("f1_score"), 3),
                "total_reviews":     len(filtered_v),
            },
            "waiver_prediction": {
                "average_calibration_error": round(sum(waiver_cal) / len(waiver_cal), 3) if waiver_cal else 0.0,
                "total_waivers": len(filtered_w),
            },
            "trend": await self._calculate_trends(violation_metrics),
        }

    async def get_dashboard(self) -> Dict:
        """Assemble data for the real-time feedback dashboard."""
        total = len(list(self.storage_path.glob("*.json")))
        daily_metrics = await self.get_metrics(days=1)
        return {
            "total_feedback_submitted": total,
            "today_metrics": daily_metrics,
            "ahj_performance":         await self._get_ahj_performance(),
            "rules_needing_attention": (await self._get_rule_accuracy_summary())["lowest_accuracy_rules"],
            "improvement_over_time":   await self._get_improvement_timeline(),
            "next_retraining_scheduled": await self._get_next_retraining_time(),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _append_metric(self, filename: str, record: Dict) -> None:
        path = self.metrics_path / filename
        entries: List[Dict] = []
        if path.exists():
            with open(path) as f:
                entries = json.load(f)
        entries.append(record)
        with open(path, "w") as f:
            json.dump(entries, f, indent=2)

    def _load_metric_file(self, filename: str) -> List[Dict]:
        path = self.metrics_path / filename
        if not path.exists():
            return []
        with open(path) as f:
            return json.load(f)

    async def _calculate_trends(self, violation_metrics: List[Dict]) -> List[Dict]:
        """Return weekly F1 averages for trend charting."""
        if not violation_metrics:
            return []

        weekly: Dict[str, List[float]] = defaultdict(list)
        for m in violation_metrics:
            week = datetime.fromisoformat(m["timestamp"]).strftime("%Y-W%W")
            weekly[week].append(m["f1_score"])

        return [
            {"week": w, "average_f1": round(sum(scores) / len(scores), 3)}
            for w, scores in sorted(weekly.items())
        ]

    async def _get_ahj_performance(self) -> List[Dict]:
        """Average F1 score grouped by AHJ name."""
        metrics = self._load_metric_file("violation_accuracy.json")
        groups: Dict[str, List[float]] = defaultdict(list)
        for m in metrics:
            groups[m.get("ahj_name", "unknown")].append(m["f1_score"])

        performance = [
            {
                "ahj_name": ahj,
                "average_f1_score": round(sum(scores) / len(scores), 3),
                "sample_size": len(scores),
            }
            for ahj, scores in groups.items()
        ]
        return sorted(performance, key=lambda x: x["average_f1_score"], reverse=True)

    async def _get_rule_accuracy_summary(self) -> Dict:
        """Return rules sorted by accuracy (lowest first)."""
        rule_path = self.metrics_path / "rule_accuracy.json"
        if not rule_path.exists():
            return {"lowest_accuracy_rules": []}

        with open(rule_path) as f:
            rule_accuracy = json.load(f)

        sorted_rules = sorted(
            [{"rule_id": k, **v} for k, v in rule_accuracy.items()],
            key=lambda x: x.get("accuracy", 1.0),
        )
        return {"lowest_accuracy_rules": sorted_rules[:10]}

    async def _get_improvement_timeline(self) -> List[Dict]:
        """Delegate to trend calculation."""
        metrics = self._load_metric_file("violation_accuracy.json")
        return await self._calculate_trends(metrics)

    async def _get_next_retraining_time(self) -> str:
        """Next scheduled retraining is daily at 02:00."""
        now = datetime.now()
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run + timedelta(days=1)
        return next_run.isoformat()
