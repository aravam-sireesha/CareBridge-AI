import os
from pathlib import Path

import joblib
import pandas as pd
import sklearn


FRAUD_MODEL_VERSION = "fraud-hgb-1.0.0"


class FraudDetector:
    def __init__(self, artifact: dict):
        self.model = artifact["model"]
        self.features = artifact["features"]
        self.threshold = float(artifact["threshold"])
        self.model_version = artifact["model_version"]
        self.metrics = artifact["metrics"]

    def score(self, values: dict[str, float]) -> dict:
        expected = set(self.features)
        supplied = set(values)
        if supplied != expected:
            missing = sorted(expected - supplied)
            unexpected = sorted(supplied - expected)
            raise ValueError(f"Feature mismatch; missing={missing}, unexpected={unexpected}")

        row = pd.DataFrame([{name: values[name] for name in self.features}])
        probability = float(self.model.predict_proba(row)[0, 1])
        return {
            "fraud_probability": probability,
            "flagged": probability >= self.threshold,
            "threshold": self.threshold,
            "model_version": self.model_version,
        }


def load_fraud_detector() -> FraudDetector | None:
    default_path = Path(__file__).resolve().parents[1] / "models" / "fraud_detector.pkl"
    model_path = Path(os.getenv("FRAUD_MODEL_PATH", default_path))
    if not model_path.exists():
        return None

    artifact = joblib.load(model_path)
    if artifact.get("model_version") != FRAUD_MODEL_VERSION:
        raise ValueError("Fraud model artifact has missing or unsupported model_version metadata")
    if artifact.get("sklearn_version") != sklearn.__version__:
        raise ValueError("Fraud model artifact scikit-learn version does not match the installed version")
    return FraudDetector(artifact)