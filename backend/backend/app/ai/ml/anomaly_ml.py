"""Anomaly detection and clustering.

* Isolation Forest  - unsupervised outlier scores for donations (amount, ratio to the donor's usual gift, burstiness, timing).
* K-Means           - donor segments from recency / frequency / monetary value (k chosen by silhouette).
* DBSCAN            - needs that sit in no dense group (outliers) and the themes that do (eps from the k-distance curve).
* K-Nearest Neighbours - the most similar past needs, with how long they took.
The existing rule-based fraud checks stay in place; these add a second, learned opinion. A person reviews every flag."""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score, silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from ...services.matching_rules import _normalize
from .dataset import URGENCY, _group_code

DONATION_FEATURES = ["log_amount", "ratio_to_donor_mean", "gifts_last_hour", "hour", "days_since_prev", "first_gift"]


# ----------------------------------------------------------------------------- Isolation Forest on donations
def donation_frame(db) -> pd.DataFrame:
    from ... import models as m
    rows = []
    by_donor: dict[int, list] = {}
    for d in db.query(m.Donation).order_by(m.Donation.timestamp).all():
        by_donor.setdefault(d.donor_id, []).append(d)
    for donor_id, gifts in by_donor.items():
        amounts = [float(g.amount or 0) for g in gifts]
        for i, g in enumerate(gifts):
            others = amounts[:i] + amounts[i + 1:]
            mean_other = float(np.mean(others)) if others else float("nan")
            ts = g.timestamp
            hour_gifts = sum(1 for h in gifts if h is not g and h.timestamp and ts and abs((h.timestamp - ts).total_seconds()) <= 3600)
            prev = [h for h in gifts[:i] if h.timestamp and ts]
            rows.append({"donation_id": g.id, "donor_id": donor_id, "amount": amounts[i], "log_amount": math.log1p(amounts[i]),
                         "ratio_to_donor_mean": (amounts[i] / mean_other) if mean_other and mean_other == mean_other else 1.0,
                         "gifts_last_hour": hour_gifts, "hour": ts.hour if ts else 12,
                         "days_since_prev": (ts - prev[-1].timestamp).total_seconds() / 86400 if prev else 365.0, "first_gift": int(not prev)})
    return pd.DataFrame(rows, columns=["donation_id", "donor_id", "amount"] + DONATION_FEATURES)


def isolation_scores(frame: pd.DataFrame, contamination: float = 0.05, seed: int = 7) -> pd.DataFrame:
    """Adds `anomaly_score` in 0..1 (1 = most unusual) and `reasons` (features far from typical)."""
    if len(frame) < 8:
        return frame.assign(anomaly_score=0.0, reasons=[[] for _ in range(len(frame))])
    X = frame[DONATION_FEATURES].astype(float).fillna(0.0)
    model = IsolationForest(n_estimators=300, contamination=contamination, random_state=seed).fit(X)
    raw = -model.score_samples(X)
    score = (raw - raw.min()) / (raw.max() - raw.min() + 1e-12)
    med, mad = X.median(), (X - X.median()).abs().median().replace(0, 1e-6)
    reasons = []
    for _, row in X.iterrows():
        z = ((row - med) / (1.4826 * mad)).abs().sort_values(ascending=False)
        reasons.append([f"{f.replace('_', ' ')} is unusual ({row[f]:.2f} vs typical {med[f]:.2f})" for f in z.index[:2] if z[f] > 3])
    return frame.assign(anomaly_score=np.round(score, 4), reasons=reasons)


def rule_scores(frame: pd.DataFrame) -> np.ndarray:
    """The existing fraud rules, vectorised, as a comparison baseline."""
    s = np.zeros(len(frame))
    s += 0.3 * (frame["donor_id"].isna()).values
    s += 0.4 * ((frame["first_gift"] == 1) & (frame["amount"] > 50000)).values
    s += 0.5 * (frame["ratio_to_donor_mean"] >= 5).values
    s += 0.4 * (frame["gifts_last_hour"] >= 3).values
    return s


def synthetic_donations(n: int = 1200, anomaly_rate: float = 0.04, seed: int = 7) -> pd.DataFrame:
    """Benchmark with injected anomalies of three kinds: huge amounts, bursts of gifts, odd-hour mid-size gifts from new donors."""
    rng = np.random.default_rng(seed)
    n_anom = int(n * anomaly_rate)
    amt = rng.lognormal(7.0, 0.7, n)
    ratio = np.clip(rng.lognormal(0.0, 0.35, n), 0.2, 4)
    burst = rng.poisson(0.15, n)
    hour = np.clip(rng.normal(14, 4, n), 0, 23).astype(int)
    prev = rng.gamma(2.0, 25.0, n)
    first = (rng.random(n) < 0.25).astype(int)
    label = np.zeros(n, dtype=int)
    idx = rng.choice(n, n_anom, replace=False)
    for k, i in enumerate(idx):
        kind = k % 3
        label[i] = 1
        if kind == 0:
            amt[i] *= rng.uniform(15, 60); ratio[i] = rng.uniform(8, 25)
        elif kind == 1:
            burst[i] = rng.integers(4, 9); prev[i] = rng.uniform(0, 0.05)
        else:
            hour[i] = rng.choice([1, 2, 3, 4]); amt[i] *= rng.uniform(4, 9); first[i] = 1; ratio[i] = rng.uniform(3, 6)
    return pd.DataFrame({"donation_id": range(n), "donor_id": rng.integers(1, 200, n), "amount": amt, "log_amount": np.log1p(amt), "ratio_to_donor_mean": ratio,
                         "gifts_last_hour": burst, "hour": hour, "days_since_prev": prev, "first_gift": first, "label": label})


def evaluate_anomaly(n: int = 1200, seed: int = 7) -> dict:
    df = synthetic_donations(n, seed=seed)
    scored = isolation_scores(df, contamination=0.04, seed=seed)
    y = df["label"].values
    k = int(y.sum())
    out = {}
    for name, s in (("isolation forest", scored["anomaly_score"].values), ("existing rules", rule_scores(df))):
        order = np.argsort(-s)[:k]
        out[name] = {"auc": round(float(roc_auc_score(y, s)), 4), "precision_at_k": round(float(y[order].mean()), 4), "recall_at_k": round(float(y[order].sum() / k), 4)}
    return {"donations": n, "anomalies": k, "k": k, "methods": out, "note": "synthetic donations with injected anomalies"}


# ----------------------------------------------------------------------------- K-Means: donor segments
def donor_segments(db, now: datetime | None = None, seed: int = 7) -> dict:
    from ... import models as m
    now = now or datetime.utcnow()
    rows = []
    for d in db.query(m.Donor).all():
        gifts = db.query(m.Donation).filter_by(donor_id=d.id).all()
        stamps = [g.timestamp for g in gifts if g.timestamp]
        rows.append({"donor_id": d.id, "name": d.name, "recency_days": (now - max(stamps)).days if stamps else 999, "frequency": len(gifts), "monetary": float(sum(g.amount or 0 for g in gifts))})
    df = pd.DataFrame(rows)
    if len(df) < 6:
        return {"k": 0, "segments": [], "donors": rows, "note": "At least 6 donors are needed for segmentation."}
    X = StandardScaler().fit_transform(np.column_stack([np.log1p(df["recency_days"]), np.log1p(df["frequency"]), np.log1p(df["monetary"])]))
    best_k, best_s, best_lab = 2, -1.0, None
    for k in range(2, min(5, len(df) - 1) + 1):
        lab = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)
        if len(set(lab)) > 1:
            sc = silhouette_score(X, lab)
            if sc > best_s:
                best_k, best_s, best_lab = k, sc, lab
    df["segment"] = best_lab
    segs = []
    overall = df[["recency_days", "frequency", "monetary"]].median()
    for c, g in df.groupby("segment"):
        cen = g[["recency_days", "frequency", "monetary"]].median()
        name = ("Lapsed" if cen["recency_days"] > max(120, 2 * overall["recency_days"]) else "High value" if cen["monetary"] > 1.5 * overall["monetary"] and cen["frequency"] >= overall["frequency"]
                else "Loyal" if cen["frequency"] > overall["frequency"] else "New or occasional")
        segs.append({"segment": int(c), "name": name, "donors": int(len(g)), "median_recency_days": float(cen["recency_days"]), "median_gifts": float(cen["frequency"]), "median_amount": float(cen["monetary"])})
        df.loc[g.index, "segment_name"] = name
    return {"k": best_k, "silhouette": round(float(best_s), 3), "segments": segs, "donors": df[["donor_id", "name", "segment_name"]].to_dict("records")}


# ----------------------------------------------------------------------------- DBSCAN: need outliers and themes
def _need_matrix(needs, now):
    cols = []
    for n in needs:
        created = n.created_at or now
        cols.append([URGENCY.get((n.urgency or "").lower(), 1), math.log1p(n.quantity or 0), min((now - created).days, 90) / 30.0, _group_code(n.category)])
    return StandardScaler().fit_transform(np.array(cols, dtype=float))


def cluster_needs(db, now: datetime | None = None) -> dict:
    from ... import models as m
    now = now or datetime.utcnow()
    needs = [n for n in db.query(m.Need).all() if (n.status or "").lower() in ("open", "pending")]
    if len(needs) < 8:
        return {"clusters": [], "outliers": [], "note": "At least 8 open needs are needed for clustering."}
    X = _need_matrix(needs, now)
    k = min(4, len(needs) - 1)
    dist = np.sort(NearestNeighbors(n_neighbors=k).fit(X).kneighbors(X)[0][:, -1])
    eps = float(np.clip(np.percentile(dist, 85), 0.3, 3.0))
    lab = DBSCAN(eps=eps, min_samples=3).fit_predict(X)
    clusters = []
    for c in sorted(set(lab) - {-1}):
        members = [n for n, l in zip(needs, lab) if l == c]
        clusters.append({"cluster": int(c), "size": len(members), "categories": sorted({_normalize(n.category) for n in members})[:5], "median_quantity": float(np.median([n.quantity or 0 for n in members]))})
    return {"eps": round(eps, 3), "clusters": clusters, "outliers": [{"need_id": n.id, "category": n.category, "quantity": n.quantity, "urgency": n.urgency} for n, l in zip(needs, lab) if l == -1]}


# ----------------------------------------------------------------------------- KNN: similar past needs
def similar_needs(db, need, k: int = 5, now: datetime | None = None) -> list[dict]:
    from ... import models as m
    now = now or datetime.utcnow()
    pool = [n for n in db.query(m.Need).all() if n.id != need.id]
    if len(pool) < 2:
        return []
    allneeds = pool + [need]
    X = _need_matrix(allneeds, now)
    nn = NearestNeighbors(n_neighbors=min(k, len(pool))).fit(X[:-1])
    dist, idx = nn.kneighbors(X[-1:])
    out = []
    for d, i in zip(dist[0], idx[0]):
        n = pool[i]
        days = None
        if n.fulfilled_at and n.created_at:
            days = round((n.fulfilled_at - n.created_at).total_seconds() / 86400, 1)
        out.append({"need_id": n.id, "category": n.category, "urgency": n.urgency, "quantity": n.quantity, "status": n.status, "days_to_fulfil": days, "distance": round(float(d), 3)})
    return out
