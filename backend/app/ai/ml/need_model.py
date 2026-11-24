"""Phase 3 - predictive ML for ONE problem: P(a need is fulfilled within 14 days).

Method: a baseline first, then candidate models on a time-ordered split. Candidates are compared by cross-validation on the training
part only; the held-out (most recent 20 percent) part is touched once, for the final report. A candidate is selected only if it
beats the baseline by a margin, otherwise the baseline stays in charge (so a fancy model can never make predictions worse).

Models: baseline (class prior per urgency), Logistic Regression, SVM (RBF), K-Nearest Neighbours, Random Forest, Gradient Boosting,
XGBoost. XGBoost and Gradient Boosting hyper-parameters are tuned by Bayesian optimisation. Explanations are model-agnostic."""
from __future__ import annotations

import json
import os
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, average_precision_score, brier_score_loss, f1_score, log_loss, mean_absolute_error, roc_auc_score
from sklearn.model_selection import RepeatedStratifiedKFold, StratifiedKFold, cross_val_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from . import bayes_opt
from .dataset import FEATURES

try:  # optional: the app works without it
    from xgboost import XGBClassifier, XGBRegressor
except Exception:  # pragma: no cover
    XGBClassifier = XGBRegressor = None

MIN_REAL_ROWS = 80
MIN_PER_CLASS = 12
MARGIN = 0.02            # a model must beat the baseline's CV AUC by this much ...
T_MIN = 2.0              # ... and the corrected paired t statistic of that difference must be at least this (about p < 0.05)
MODEL_DIR = Path(os.getenv("AI_MODEL_DIR", "data/models"))


class UrgencyPrior(ClassifierMixin, BaseEstimator):
    """Baseline: the observed fulfilment rate of each urgency level (a rule of thumb any administrator could apply)."""
    def fit(self, X, y):
        X = pd.DataFrame(X, columns=FEATURES) if not isinstance(X, pd.DataFrame) else X
        y = np.asarray(y)
        self.global_ = float(np.mean(y)) if len(y) else 0.5
        self.table_ = {int(u): (float(y[X["urgency"].values == u].mean()) if (X["urgency"].values == u).sum() >= 5 else self.global_) for u in np.unique(X["urgency"])}
        self.classes_ = np.array([0, 1])
        return self

    def predict_proba(self, X):
        X = pd.DataFrame(X, columns=FEATURES) if not isinstance(X, pd.DataFrame) else X
        p = np.array([self.table_.get(int(u), self.global_) for u in X["urgency"].values])
        return np.column_stack([1 - p, p])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def _candidates(seed: int, tuned: dict | None = None) -> dict:
    tuned = tuned or {}
    out = {
        "baseline (urgency prior)": UrgencyPrior(),
        "logistic regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=1.0)),
        "svm (rbf)": make_pipeline(StandardScaler(), CalibratedClassifierCV(SVC(kernel="rbf", C=2.0, random_state=seed), ensemble=False, cv=3)),
        "k-nearest neighbours": make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=25, weights="distance")),
        "random forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=3, random_state=seed, n_jobs=1),
        "gradient boosting": GradientBoostingClassifier(random_state=seed, **tuned.get("gradient boosting", {"n_estimators": 150, "max_depth": 3, "learning_rate": 0.08, "subsample": 0.9})),
    }
    if XGBClassifier is not None:
        out["xgboost"] = XGBClassifier(random_state=seed, eval_metric="logloss", n_jobs=1, verbosity=0,
                                       **tuned.get("xgboost", {"n_estimators": 200, "max_depth": 3, "learning_rate": 0.08, "subsample": 0.9}))
    return out


def ece(y, p, bins: int = 10) -> float:
    """Expected calibration error: how far predicted probabilities are from observed frequencies."""
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if mask.any():
            total += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return float(total)


def metrics(y, p) -> dict:
    y, p = np.asarray(y), np.clip(np.asarray(p), 1e-6, 1 - 1e-6)
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4), "pr_auc": round(float(average_precision_score(y, p)), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "log_loss": round(float(log_loss(y, p)), 4), "accuracy": round(float(accuracy_score(y, p >= 0.5)), 4), "f1": round(float(f1_score(y, p >= 0.5)), 4), "ece": round(ece(y, p), 4)}


def bootstrap_auc_ci(y, p, n: int = 300, seed: int = 7) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    y, p = np.asarray(y), np.asarray(p)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx])) == 2:
            vals.append(roc_auc_score(y[idx], p[idx]))
    return (round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)) if vals else (float("nan"), float("nan"))


def time_split(df: pd.DataFrame, test_frac: float = 0.2):
    df = df.sort_values("created_at").reset_index(drop=True)
    cut = int(len(df) * (1 - test_frac))
    return df.iloc[:cut], df.iloc[cut:]


def tune(X, y, seed: int = 7, n_iter: int = 10) -> dict:
    """Bayesian optimisation of the two boosting models, scored by 3-fold CV AUC on the TRAINING part only."""
    cv = StratifiedKFold(3, shuffle=True, random_state=seed)
    tuned: dict = {}
    space = {"n_estimators": (60, 300, "int"), "max_depth": (2, 6, "int"), "learning_rate": (0.02, 0.3, "log"), "subsample": (0.6, 1.0, "float")}
    makers = {"gradient boosting": lambda **p: GradientBoostingClassifier(random_state=seed, **p)}
    if XGBClassifier is not None:
        makers["xgboost"] = lambda **p: XGBClassifier(random_state=seed, eval_metric="logloss", n_jobs=1, verbosity=0, **p)
    for name, make in makers.items():
        res = bayes_opt.minimize(lambda **p: -cross_val_score(make(**p), X, y, cv=cv, scoring="roc_auc").mean(), space, n_init=4, n_iter=n_iter, seed=seed)
        tuned[name] = res.best_x
        tuned[name + " history"] = [round(-v, 4) for _, v in res.history]
    return tuned


def compare(df: pd.DataFrame, seed: int = 7, test_frac: float = 0.2, tune_models: bool = True, cv_folds: int = 5, n_iter: int = 10) -> dict:
    """Compare every candidate. Selection uses CV on the training part; the held-out part is only used to report."""
    warnings.filterwarnings("ignore")
    train, test = time_split(df, test_frac)
    X_tr, y_tr, X_te, y_te = train[FEATURES], train["label"].values, test[FEATURES], test["label"].values
    oracle = round(float(roc_auc_score(y_te, test["true_probability"])), 4) if "true_probability" in test else None
    tuned = tune(X_tr, y_tr, seed, n_iter) if tune_models else {}
    repeats = 3
    cv = RepeatedStratifiedKFold(n_splits=cv_folds, n_repeats=repeats, random_state=seed)   # identical folds for every model: paired comparison
    rows, fitted, fold_scores = [], {}, {}
    for name, model in _candidates(seed, tuned).items():
        t0 = time.time()
        scores = cross_val_score(model, X_tr, y_tr, cv=cv, scoring="roc_auc")
        fold_scores[name] = scores
        model.fit(X_tr, y_tr)
        p = model.predict_proba(X_te)[:, 1]
        fitted[name] = (model, p)
        rows.append({"model": name, "cv_auc_mean": round(float(scores.mean()), 4), "cv_auc_std": round(float(scores.std()), 4), **{f"test_{k}": v for k, v in metrics(y_te, p).items()},
                     "seconds": round(time.time() - t0, 2)})
    base = next(r for r in rows if r["model"].startswith("baseline"))
    best = max((r for r in rows if not r["model"].startswith("baseline")), key=lambda r: r["cv_auc_mean"])
    d = fold_scores[best["model"]] - fold_scores[base["model"]]
    k = len(d)
    n_tr = max(len(X_tr), 1)
    var = float(np.var(d, ddof=1)) if k > 1 else 0.0
    corrected = (1.0 / k + (1.0 / cv_folds) / (1 - 1.0 / cv_folds)) * var      # Nadeau & Bengio: folds overlap, so the plain variance is too small
    t_stat = float(d.mean() / np.sqrt(corrected)) if corrected > 0 else float("inf") if d.mean() > 0 else 0.0
    use_best = bool(d.mean() >= MARGIN and t_stat >= T_MIN)
    selected = best["model"] if use_best else base["model"]
    y_p = fitted[selected][1]
    lo, hi = bootstrap_auc_ci(y_te, y_p, seed=seed)
    b_lo, b_hi = bootstrap_auc_ci(y_te, fitted[base["model"]][1], seed=seed)
    return {"rows": len(df), "train_rows": len(train), "test_rows": len(test), "positive_rate": round(float(df["label"].mean()), 3), "table": sorted(rows, key=lambda r: -r["cv_auc_mean"]),
            "selected": selected, "beat_baseline": use_best, "paired_t": round(t_stat, 2), "auc_gain_over_baseline": round(float(d.mean()), 4),
            "selection_rule": f"mean CV AUC gain >= {MARGIN} and corrected paired t >= {T_MIN} over {k} folds (all models share the same folds)",
            "oracle_test_auc": oracle, "selected_test_auc_ci95": [lo, hi], "baseline_test_auc_ci95": [b_lo, b_hi], "tuned": {k: v for k, v in tuned.items() if not k.endswith("history")},
            "tuning_history": {k: v for k, v in tuned.items() if k.endswith("history")}, "_model": fitted[selected][0], "_X_train": X_tr}


def compare_regression(df: pd.DataFrame, seed: int = 7) -> dict:
    """Secondary: expected days to fulfil, for needs that were fulfilled. Linear / Ridge regression vs tree ensembles."""
    d = df.dropna(subset=["days_to_fulfil"])
    d = d[d["label"].notna()]
    d = d[d["days_to_fulfil"] < 120]
    train, test = time_split(d)
    X_tr, y_tr, X_te, y_te = train[FEATURES], np.log1p(train["days_to_fulfil"]), test[FEATURES], test["days_to_fulfil"].values
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    models = {"mean baseline": None, "linear regression": make_pipeline(StandardScaler(), LinearRegression()), "ridge regression": make_pipeline(StandardScaler(), Ridge(alpha=3.0)),
              "random forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=3, random_state=seed), "gradient boosting": GradientBoostingRegressor(random_state=seed, n_estimators=150, max_depth=3)}
    if XGBRegressor is not None:
        models["xgboost"] = XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.08, subsample=0.9, random_state=seed, verbosity=0, n_jobs=1)
    rows = []
    for name, mdl in models.items():
        pred = np.full(len(y_te), float(np.expm1(y_tr.mean()))) if mdl is None else np.expm1(mdl.fit(X_tr, y_tr).predict(X_te))
        rows.append({"model": name, "test_mae_days": round(float(mean_absolute_error(y_te, pred)), 2)})
    return {"rows": len(d), "table": sorted(rows, key=lambda r: r["test_mae_days"])}


# ----------------------------------------------------------------------------- persistence, prediction, explanation
def _paths(name: str = "need_fulfilment"):
    return MODEL_DIR / f"{name}.joblib", MODEL_DIR / f"{name}.json"


def save(report: dict, trained_on: str, name: str = "need_fulfilment") -> dict:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path, meta_path = _paths(name)
    X = report["_X_train"]
    meta = {"selected": report["selected"], "beat_baseline": report["beat_baseline"], "trained_on": trained_on, "rows": report["rows"], "trained_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "features": FEATURES, "medians": {c: float(X[c].median()) for c in FEATURES}, "table": report["table"], "ci95": report["selected_test_auc_ci95"]}
    joblib.dump(report["_model"], model_path)
    meta_path.write_text(json.dumps(meta, indent=1))
    return meta


def load(name: str = "need_fulfilment"):
    model_path, meta_path = _paths(name)
    if not (model_path.exists() and meta_path.exists()):
        return None, None
    try:
        return joblib.load(model_path), json.loads(meta_path.read_text())
    except Exception:
        return None, None


def explain(model, row: dict, medians: dict, top: int = 3) -> list[dict]:
    """Model-agnostic: how much does the probability move if one feature is replaced by its typical (median) value?"""
    x = pd.DataFrame([row], columns=FEATURES)
    base = float(model.predict_proba(x)[0, 1])
    out = []
    for f in FEATURES:
        y = x.copy()
        y[f] = medians.get(f, 0.0)
        out.append({"feature": f, "value": round(float(row[f]), 3), "effect": round(base - float(model.predict_proba(y)[0, 1]), 4)})
    return sorted(out, key=lambda e: -abs(e["effect"]))[:top]


def risk_label(p: float) -> str:
    return "low" if p >= 0.65 else "medium" if p >= 0.4 else "high"   # risk of NOT being fulfilled in time


def predict(db, need, now: datetime | None = None) -> dict:
    """Probability that the need is fulfilled within 14 days, with the model used and the main factors."""
    from .dataset import need_features, build_context, training_frame
    now = now or datetime.utcnow()
    row = need_features(db, need, now, build_context(db))
    model, meta = load()
    if model is None:
        frame = training_frame(db, now)
        prior = UrgencyPrior().fit(frame[FEATURES], frame["label"]) if len(frame) >= 5 else None
        p = float(prior.predict_proba(pd.DataFrame([row], columns=FEATURES))[0, 1]) if prior else 0.5
        return {"need_id": need.id, "probability": round(p, 3), "risk": risk_label(p), "model": "baseline (urgency prior)" if prior else "no data (0.5)",
                "trained_on": f"{len(frame)} real labelled needs", "factors": [], "note": "Too little history to train a model; this is the baseline."}
    p = float(model.predict_proba(pd.DataFrame([row], columns=FEATURES))[0, 1])
    return {"need_id": need.id, "probability": round(p, 3), "risk": risk_label(p), "model": meta["selected"], "trained_on": f"{meta['rows']} {meta['trained_on']} needs",
            "factors": explain(model, row, meta["medians"]), "note": "Probability of being fulfilled within 14 days."}


def train_from_db(db, now: datetime | None = None, seed: int = 7) -> dict:
    """Train on REAL data only when there is enough; otherwise report why not."""
    from .dataset import training_frame
    frame = training_frame(db, now)
    pos, neg = int(frame["label"].sum()), int((1 - frame["label"]).sum()) if len(frame) else 0
    if len(frame) < MIN_REAL_ROWS or min(pos, neg) < MIN_PER_CLASS:
        return {"trained": False, "rows": len(frame), "positives": pos, "negatives": neg,
                "reason": f"Needs at least {MIN_REAL_ROWS} labelled needs with {MIN_PER_CLASS} of each outcome; the baseline stays in use."}
    rep = compare(frame, seed=seed, n_iter=8)
    meta = save(rep, "real")
    return {"trained": True, "rows": len(frame), "selected": rep["selected"], "beat_baseline": rep["beat_baseline"], "table": rep["table"], "meta": meta}
