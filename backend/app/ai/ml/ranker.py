"""Learning to rank: learn from administrators' approve / reject decisions how to order donor and volunteer candidates for a need.

Candidates for one need form a group. Models compared by NDCG@3 on held-out needs: the existing weighted score (baseline),
a pairwise logistic ranker (RankNet style) and XGBoost's LambdaMART (rank:ndcg). Until enough decisions exist the weighted score
stays in use. The weights of the baseline can themselves be tuned with Bayesian optimisation (see tune_weights)."""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ndcg_score

from . import bayes_opt

try:
    from xgboost import XGBRanker
except Exception:  # pragma: no cover
    XGBRanker = None

DONOR_FEATURES = ["text_sim", "group_match", "history", "recency", "reliability", "location"]
MIN_GROUPS = 20


def weighted_score(X: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
    """The existing hand-set weighting: 0.6 group_match + 0.4 text_sim relevance, then history, recency, reliability."""
    w = np.array([0.22, 0.33, 0.20, 0.10, 0.15, 0.0]) if w is None else w
    return X @ w


def synthetic_groups(n_groups: int = 400, per: int = 8, seed: int = 7):
    """Candidates whose true usefulness is non-linear: a strong category match only helps when the donor is also reliable."""
    rng = np.random.default_rng(seed)
    X = rng.random((n_groups * per, len(DONOR_FEATURES)))
    X[:, 1] = np.where(rng.random(len(X)) < 0.5, 0.0, X[:, 1])
    util = 1.4 * X[:, 1] * X[:, 4] + 0.6 * X[:, 0] + 0.5 * X[:, 3] * X[:, 2] + 0.4 * X[:, 5] - 0.5 + rng.normal(0, 0.18, len(X))
    y = (util > np.quantile(util, 0.7)).astype(int)
    g = np.repeat(np.arange(n_groups), per)
    return X, y, g


def _group_ndcg(model_scores, y, g, k=3) -> float:
    out = []
    for gid in np.unique(g):
        m = g == gid
        if y[m].sum() > 0 and m.sum() > 1:
            out.append(ndcg_score([y[m]], [model_scores[m]], k=k))
    return float(np.mean(out)) if out else float("nan")


class PairwiseRanker:
    """RankNet-style: logistic regression on the difference between a relevant and a non-relevant candidate of the same need."""
    def fit(self, X, y, g):
        diffs, labels = [], []
        for gid in np.unique(g):
            m = g == gid
            pos, neg = X[m & (y == 1)], X[m & (y == 0)]
            for p in pos:
                for n in neg:
                    diffs += [p - n, n - p]
                    labels += [1, 0]
        self.lr = LogisticRegression(max_iter=1000, C=2.0).fit(np.array(diffs), np.array(labels))
        return self

    def score(self, X):
        return X @ self.lr.coef_[0]


def compare(X: np.ndarray, y: np.ndarray, g: np.ndarray, seed: int = 7, k: int = 3) -> dict:
    groups = np.unique(g)
    rng = np.random.default_rng(seed)
    rng.shuffle(groups)
    test_groups = set(groups[: max(1, len(groups) // 4)])
    te = np.array([gid in test_groups for gid in g])
    Xtr, ytr, gtr, Xte, yte, gte = X[~te], y[~te], g[~te], X[te], y[te], g[te]
    rows = [{"model": "weighted score (baseline)", f"ndcg@{k}": round(_group_ndcg(weighted_score(Xte), yte, gte, k), 4)}]
    pr = PairwiseRanker().fit(Xtr, ytr, gtr)
    rows.append({"model": "pairwise logistic (RankNet-style)", f"ndcg@{k}": round(_group_ndcg(pr.score(Xte), yte, gte, k), 4)})
    fitted = {"pairwise": pr}
    if XGBRanker is not None:
        order = np.argsort(gtr, kind="stable")
        sizes = np.bincount(np.searchsorted(np.unique(gtr), gtr[order]))
        xr = XGBRanker(objective="rank:ndcg", n_estimators=150, max_depth=3, learning_rate=0.1, random_state=seed, n_jobs=1, verbosity=0)
        xr.fit(Xtr[order], ytr[order], group=sizes)
        rows.append({"model": "xgboost lambdamart", f"ndcg@{k}": round(_group_ndcg(xr.predict(Xte), yte, gte, k), 4)})
        fitted["xgboost"] = xr
    rows.sort(key=lambda r: -r[f"ndcg@{k}"])
    return {"groups": int(len(groups)), "test_groups": len(test_groups), "candidates": int(len(y)), "table": rows, "_fitted": fitted}


def tune_weights(X, y, g, n_iter: int = 15, seed: int = 7) -> dict:
    """Bayesian optimisation of the baseline's six weights, maximising NDCG@3 on the training groups."""
    space = {f"w{i}": (0.0, 1.0, "float") for i in range(X.shape[1])}
    res = bayes_opt.minimize(lambda **p: -_group_ndcg(weighted_score(X, np.array([p[f"w{i}"] for i in range(X.shape[1])])), y, g), space, n_init=6, n_iter=n_iter, seed=seed)
    w = np.array([res.best_x[f"w{i}"] for i in range(X.shape[1])])
    return {"weights": [round(float(x), 3) for x in w / (w.sum() or 1)], "train_ndcg": round(-res.best_value, 4)}


def from_db(db, kind: str = "donor") -> dict:
    """Judged candidates from administrator decisions. Returns the arrays, or why there are not enough."""
    from ... import models as m
    model = m.DonorSuggestion if kind == "donor" else m.VolunteerSuggestion
    rows = db.query(model).filter(model.status != "suggested", model.features.isnot(None)).all()
    X, y, g = [], [], []
    for r in rows:
        f = r.features or {}
        X.append([f.get(k, 0.0) for k in DONOR_FEATURES])
        y.append(1 if r.status in ("approved", "contacted") else 0)
        g.append(r.need_id)
    g_arr = np.array(g)
    usable = [gid for gid in set(g) if 0 < sum(1 for a, b in zip(g, y) if a == gid and b == 1) < sum(1 for a in g if a == gid)]
    if len(usable) < MIN_GROUPS:
        return {"enough": False, "groups": len(usable), "needed": MIN_GROUPS}
    keep = np.isin(g_arr, usable)
    return {"enough": True, "X": np.array(X)[keep], "y": np.array(y)[keep], "g": g_arr[keep], "groups": len(usable)}
