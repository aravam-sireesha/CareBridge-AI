from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve, precision_score, recall_score
from sklearn.model_selection import train_test_split


FRAUD_MODEL_VERSION = "fraud-hgb-1.0.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "raw" / "fraud" / "creditcard.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "fraud_detector.pkl"


def train_fraud_model(data_path: Path = DATA_PATH, model_path: Path = MODEL_PATH) -> dict:
    transactions = pd.read_csv(data_path)
    features = [column for column in transactions.columns if column != "Class"]
    X = transactions[features]
    y = transactions["Class"]

    X_train_validation, X_test, y_train_validation, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    X_train, X_validation, y_train, y_validation = train_test_split(
        X_train_validation,
        y_train_validation,
        test_size=0.25,
        random_state=42,
        stratify=y_train_validation,
    )

    model = HistGradientBoostingClassifier(
        class_weight="balanced",
        l2_regularization=1.0,
        max_iter=200,
        max_leaf_nodes=15,
        random_state=42,
    )
    model.fit(X_train, y_train)

    validation_probabilities = model.predict_proba(X_validation)[:, 1]
    precision, recall, thresholds = precision_recall_curve(y_validation, validation_probabilities)
    f1_scores = 2 * precision[:-1] * recall[:-1] / (precision[:-1] + recall[:-1] + 1e-12)
    threshold = float(thresholds[int(np.nanargmax(f1_scores))])

    test_probabilities = model.predict_proba(X_test)[:, 1]
    test_predictions = test_probabilities >= threshold
    metrics = {
        "precision": float(precision_score(y_test, test_predictions, zero_division=0)),
        "recall": float(recall_score(y_test, test_predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(y_test, test_probabilities)),
        "threshold": threshold,
        "test_fraud_prevalence": float(y_test.mean()),
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": features,
            "threshold": threshold,
            "metrics": metrics,
            "model_version": FRAUD_MODEL_VERSION,
            "sklearn_version": sklearn.__version__,
        },
        model_path,
    )
    return metrics


if __name__ == "__main__":
    print(train_fraud_model())