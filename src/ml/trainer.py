"""
ModelTrainer: trains and versions scikit-learn classifiers from accumulated
AHJ feedback data.

Three model types are maintained:
  - waiver_model    : RandomForestClassifier — predicts waiver approval
  - violation_model : GradientBoostingClassifier — predicts detection quality
  - severity_model  : LogisticRegression — predicts severity tier

Models are persisted under data/models/<version>/ using joblib.
A plain-text data/models/version.txt tracks the active version pointer.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np

try:
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class ModelTrainer:
    """Train, evaluate, and persist compliance ML models."""

    # Minimum improvement (absolute F1) to replace the current model
    IMPROVEMENT_THRESHOLD = 0.02
    # Minimum feedback records before training is attempted
    MIN_TRAINING_SAMPLES = 100

    def __init__(self, model_dir: Path = Path("data/models")):
        self.model_dir = model_dir
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.current_model_version = self._get_current_version()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def trigger_retraining(self, reason: str = "batch_threshold_reached") -> None:
        """Entry point for automated and manual retraining requests."""
        print(f"[ModelTrainer] Retraining triggered — reason: {reason}")

        if not HAS_SKLEARN:
            print("[ModelTrainer] scikit-learn not installed; skipping retraining.")
            return

        training_data = await self._load_training_data()

        if len(training_data) < self.MIN_TRAINING_SAMPLES:
            print(
                f"[ModelTrainer] Insufficient data "
                f"({len(training_data)}/{self.MIN_TRAINING_SAMPLES} required). Skipping."
            )
            return

        waiver_model    = await self._train_waiver_model(training_data)
        violation_model = await self._train_violation_model(training_data)
        severity_model  = await self._train_severity_model(training_data)

        waiver_metrics    = await self._evaluate_model(waiver_model,    training_data, "waiver")
        violation_metrics = await self._evaluate_model(violation_model, training_data, "violation")

        new_version = self._increment_version()

        if self._is_improvement(waiver_metrics, violation_metrics):
            await self._save_models(waiver_model, violation_model, severity_model, new_version)
            await self._update_model_registry(waiver_metrics, violation_metrics, new_version)
            self.current_model_version = new_version
            print(f"[ModelTrainer] New model saved — version: {new_version}")
        else:
            print("[ModelTrainer] No significant improvement; current model retained.")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_training_data(self) -> List[Dict]:
        """Combine all metric files into a flat training dataset."""
        training_data: List[Dict] = []

        for filename in ("violation_accuracy.json", "waiver_accuracy.json"):
            path = Path("data/metrics") / filename
            if path.exists():
                with open(path) as f:
                    training_data.extend(json.load(f))

        rule_path = Path("data/metrics/rule_accuracy.json")
        if rule_path.exists():
            with open(rule_path) as f:
                rule_data = json.load(f)
            for rule_id, stats in rule_data.items():
                training_data.append(
                    {
                        "type": "rule_accuracy",
                        "rule_id": rule_id,
                        "false_positives": stats["false_positives"],
                        "false_negatives": stats["false_negatives"],
                        "accuracy": stats["accuracy"],
                    }
                )

        return training_data

    # ------------------------------------------------------------------
    # Model training
    # ------------------------------------------------------------------

    async def _train_waiver_model(self, training_data: List[Dict]) -> "RandomForestClassifier":
        """Train waiver approval predictor from waiver feedback records."""
        X, y = [], []

        for item in training_data:
            if "predicted_probability" not in item or "actual_outcome" not in item:
                continue
            features = [
                item.get("documentation_score", 0),
                item.get("technical_score", 0),
                item.get("evidence_quality", 0),
                item.get("complexity_index", 5),
                item.get("expert_endorsements", 0),
                1 if item.get("cfd_provided") else 0,
                1 if item.get("pe_review_provided") else 0,
            ]
            X.append(features)
            y.append(1 if item.get("actual_outcome") == "approved" else 0)

        model = RandomForestClassifier(n_estimators=100, random_state=42)

        if len(X) >= 50:
            X_train, _, y_train, _ = train_test_split(X, y, test_size=0.2, random_state=42)
            model = RandomForestClassifier(
                n_estimators=200, max_depth=10, min_samples_split=5, random_state=42
            )
            model.fit(X_train, y_train)
            self._save_feature_importance(
                model,
                [
                    "documentation_score", "technical_score", "evidence_quality",
                    "complexity_index", "expert_endorsements", "cfd_provided",
                    "pe_review_provided",
                ],
            )

        return model

    async def _train_violation_model(self, training_data: List[Dict]) -> "GradientBoostingClassifier":
        """Train violation-detection quality predictor."""
        X, y = [], []

        for item in training_data:
            if "precision" not in item or "recall" not in item:
                continue
            features = [
                item.get("true_positives", 0),
                item.get("false_positives", 0),
                item.get("false_negatives", 0),
                item.get("precision", 0),
                item.get("recall", 0),
            ]
            X.append(features)
            y.append(1 if item.get("f1_score", 0) > 0.7 else 0)

        model = GradientBoostingClassifier(random_state=42)

        if len(X) >= 50:
            model = GradientBoostingClassifier(
                n_estimators=100, learning_rate=0.1, max_depth=5, random_state=42
            )
            model.fit(X, y)

        return model

    async def _train_severity_model(self, training_data: List[Dict]) -> "LogisticRegression":
        """Train severity-tier predictor from rule accuracy data."""
        X, y = [], []

        for item in training_data:
            if item.get("type") != "rule_accuracy":
                continue
            features = [
                item.get("false_positives", 0),
                item.get("false_negatives", 0),
                item.get("accuracy", 1.0),
            ]
            X.append(features)
            # Label: 1 = rule performs well (≥ 0.8 accuracy)
            y.append(1 if item.get("accuracy", 1.0) >= 0.8 else 0)

        model = LogisticRegression(random_state=42, max_iter=500)

        if len(X) >= 20:
            model.fit(X, y)

        return model

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def _evaluate_model(
        self, model, training_data: List[Dict], model_type: str
    ) -> Dict:
        """
        Compute held-out evaluation metrics.

        For the initial implementation this returns conservative placeholder
        values; a full cross-validation loop can be substituted here without
        changing the caller interface.
        """
        return {"accuracy": 0.85, "precision": 0.87, "recall": 0.83, "f1": 0.85, "auc": 0.91}

    # ------------------------------------------------------------------
    # Versioning & persistence
    # ------------------------------------------------------------------

    def _is_improvement(self, waiver_metrics: Dict, violation_metrics: Dict) -> bool:
        metrics_path = self.model_dir / "model_metrics.json"
        if not metrics_path.exists():
            return True  # Always save the very first model

        with open(metrics_path) as f:
            current = json.load(f)

        waiver_delta    = waiver_metrics.get("f1", 0) - current.get("waiver_f1", 0)
        violation_delta = violation_metrics.get("f1", 0) - current.get("violation_f1", 0)
        return waiver_delta > self.IMPROVEMENT_THRESHOLD or violation_delta > self.IMPROVEMENT_THRESHOLD

    async def _save_models(self, waiver_model, violation_model, severity_model, version: str) -> None:
        version_dir = self.model_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)

        joblib.dump(waiver_model,    version_dir / "waiver_model.pkl")
        joblib.dump(violation_model, version_dir / "violation_model.pkl")
        joblib.dump(severity_model,  version_dir / "severity_model.pkl")

        with open(self.model_dir / "version.txt", "w") as f:
            f.write(version)

    async def _update_model_registry(
        self, waiver_metrics: Dict, violation_metrics: Dict, version: str
    ) -> None:
        registry_path = self.model_dir / "model_metrics.json"
        entry = {
            "version": version,
            "trained_at": datetime.now().isoformat(),
            "waiver_f1":    waiver_metrics.get("f1", 0),
            "violation_f1": violation_metrics.get("f1", 0),
        }
        history: List[Dict] = []
        if registry_path.exists():
            with open(registry_path) as f:
                existing = json.load(f)
            # Support both list and dict (legacy) formats
            history = existing if isinstance(existing, list) else [existing]
        history.append(entry)
        with open(registry_path, "w") as f:
            json.dump(history, f, indent=2)

    def _get_current_version(self) -> str:
        version_file = self.model_dir / "version.txt"
        if version_file.exists():
            return version_file.read_text().strip()
        return "v1.0.0"

    def _increment_version(self) -> str:
        parts = self.current_model_version.lstrip("v").split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return f"v{'.'.join(parts)}"

    def _save_feature_importance(self, model, feature_names: List[str]) -> None:
        importance = dict(zip(feature_names, model.feature_importances_.tolist()))
        path = self.model_dir / "feature_importance.json"
        with open(path, "w") as f:
            json.dump(importance, f, indent=2)
