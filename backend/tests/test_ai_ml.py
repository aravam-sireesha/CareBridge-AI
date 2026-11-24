"""Phase 3: predictive ML - one problem, baseline first, honest evaluation, guard rails."""
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as m
from app.ai.ml import anomaly_ml as am
from app.ai.ml import bayes_net, bayes_opt, dataset, forecast_models as fm, need_model, ranker, simulate
from app.database import Base

warnings.filterwarnings("ignore")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


# ----------------------------------------------------------------------------- Bayesian optimisation
def test_bayesian_optimisation_beats_random_search_with_the_same_budget():
    f = lambda x, y: (x - 0.3) ** 2 + (y - 0.7) ** 2  # noqa: E731
    space = {"x": (0.0, 1.0, "float"), "y": (0.0, 1.0, "float")}
    res = bayes_opt.minimize(f, space, n_init=4, n_iter=14, seed=3)
    rng = np.random.default_rng(3)
    random_best = min(f(*rng.random(2)) for _ in range(18))
    assert res.best_value < 0.01 and res.best_value <= random_best and len(res.history) == 18
    again = bayes_opt.minimize(f, space, n_init=4, n_iter=14, seed=3)
    assert again.best_x == res.best_x                                   # reproducible
    ints = bayes_opt.minimize(lambda n, lr: abs(n - 7) + lr, {"n": (1, 20, "int"), "lr": (0.001, 1.0, "log")}, n_init=4, n_iter=6, seed=1)
    assert isinstance(ints.best_x["n"], int) and 0.001 <= ints.best_x["lr"] <= 1.0


# ----------------------------------------------------------------------------- the dataset
def test_synthetic_benchmark_is_labelled_balanced_enough_and_documented():
    df = dataset.synthetic(800)
    assert list(df[dataset.FEATURES].columns) == dataset.FEATURES and 0.3 < df["label"].mean() < 0.9 and df["true_probability"].between(0, 1).all()
    assert df["created_at"].is_monotonic_increasing and df["urgency"].between(0, 3).all()


def test_real_labels_censor_young_needs_and_use_only_posting_time_features(db):
    now = datetime(2026, 6, 30)
    org = m.Organization(name="Hope", contact="c", verified=True)
    db.add(org)
    db.flush()
    mk = lambda days_ago, status, done_after=None, **kw: m.Need(org_id=org.id, category="Books", quantity=20, urgency="high", status=status, created_at=now - timedelta(days=days_ago),  # noqa: E731
                                                                fulfilled_at=(now - timedelta(days=days_ago) + timedelta(days=done_after)) if done_after is not None else None, **kw)
    db.add_all([mk(40, "fulfilled", 5), mk(40, "fulfilled", 25), mk(40, "open"), mk(5, "open"), mk(40, "closed")])
    db.commit()
    frame = dataset.training_frame(db, now)
    assert sorted(frame["label"].tolist()) == [0, 0, 1]                     # quick=1, slow=0, ignored-for-40-days=0; the 5-day-old open need and the closed one are left out
    assert frame["days_to_fulfil"].dropna().tolist() == [5.0, 25.0] or sorted(frame["days_to_fulfil"].dropna().tolist()) == [5.0, 25.0]
    assert not {"label", "days_to_fulfil", "fulfilled_at"} & set(dataset.FEATURES)   # nothing from the outcome is a feature


# ----------------------------------------------------------------------------- model comparison and guard rails
def test_comparison_reports_every_model_a_baseline_and_honest_uncertainty():
    df = dataset.synthetic(700)
    rep = need_model.compare(df, tune_models=False, cv_folds=3)
    names = {r["model"] for r in rep["table"]}
    assert {"baseline (urgency prior)", "logistic regression", "random forest", "gradient boosting", "svm (rbf)", "k-nearest neighbours"} <= names
    assert "xgboost" in names                                               # installed in this environment
    assert rep["train_rows"] + rep["test_rows"] == 700 and rep["test_rows"] == 140                       # time-ordered 80/20 split
    lo, hi = rep["selected_test_auc_ci95"]
    assert 0.4 < lo < hi < 1.0 and rep["oracle_test_auc"] > 0.6
    row = [r for r in rep["table"] if r["model"] == rep["selected"]][0]
    assert row["test_roc_auc"] > 0.55 and 0 <= row["test_ece"] < 0.2 and rep["beat_baseline"] is True


def test_a_model_with_no_real_signal_never_replaces_the_baseline():
    rng = np.random.default_rng(1)
    df = dataset.synthetic(600)
    df["label"] = rng.integers(0, 2, len(df))                               # outcomes unrelated to every feature
    rep = need_model.compare(df, tune_models=False, cv_folds=3)
    assert rep["beat_baseline"] is False and rep["selected"].startswith("baseline")


def test_a_small_noisy_win_over_the_baseline_is_not_enough_to_replace_it():
    """When urgency alone generates the outcome the baseline IS the true model; any candidate's CV edge is noise and must be rejected."""
    rng = np.random.default_rng(5)
    df = dataset.synthetic(180, seed=5)
    p = np.array([0.25, 0.4, 0.6, 0.8])[df["urgency"].values]
    df["label"] = (rng.random(len(df)) < p).astype(int)
    rep = need_model.compare(df, tune_models=False, cv_folds=5)
    assert rep["beat_baseline"] is False and rep["selected"].startswith("baseline") and "paired t" in rep["selection_rule"]
    clear = need_model.compare(dataset.synthetic(900), tune_models=False, cv_folds=5)
    assert clear["beat_baseline"] is True and clear["paired_t"] >= need_model.T_MIN and clear["auc_gain_over_baseline"] >= need_model.MARGIN


def test_tuning_records_a_history_and_does_not_look_at_the_test_split():
    df = dataset.synthetic(500)
    rep = need_model.compare(df, tune_models=True, cv_folds=3, n_iter=3)
    assert set(rep["tuned"]) >= {"gradient boosting", "xgboost"} and len(rep["tuning_history"]["xgboost history"]) == 7
    assert rep["tuned"]["xgboost"]["max_depth"] in range(2, 7)


def test_regression_secondary_problem_is_compared_against_a_mean_baseline():
    rep = need_model.compare_regression(dataset.synthetic(600))
    assert {"mean baseline", "linear regression", "ridge regression", "random forest", "xgboost"} <= {r["model"] for r in rep["table"]}
    assert all(r["test_mae_days"] > 0 for r in rep["table"])


def test_training_on_real_data_needs_enough_rows_and_both_outcomes(db, monkeypatch, tmp_path):
    monkeypatch.setattr(need_model, "MODEL_DIR", tmp_path)
    out = need_model.train_from_db(db)
    assert out["trained"] is False and "at least" in out["reason"].lower()
    monkeypatch.setattr(dataset, "training_frame", lambda db, now=None, horizon_days=14: dataset.synthetic(400))
    ok = need_model.train_from_db(db)
    assert ok["trained"] is True and (tmp_path / "need_fulfilment.joblib").exists() and ok["meta"]["trained_on"] == "real"


def test_prediction_uses_the_baseline_without_a_model_and_explains_with_one(db, monkeypatch, tmp_path):
    monkeypatch.setattr(need_model, "MODEL_DIR", tmp_path)
    org = m.Organization(name="Hope", contact="c", verified=True)
    db.add(org)
    db.flush()
    need = m.Need(org_id=org.id, category="Books", quantity=30, urgency="critical", status="open", created_at=datetime.utcnow())
    db.add(need)
    db.commit()
    p0 = need_model.predict(db, need)
    assert p0["model"].startswith(("no data", "baseline")) and 0 <= p0["probability"] <= 1 and p0["factors"] == []
    rep = need_model.compare(dataset.synthetic(600), tune_models=False, cv_folds=3)
    need_model.save(rep, "synthetic")
    p1 = need_model.predict(db, need)
    assert p1["model"] == rep["selected"] and len(p1["factors"]) == 3 and p1["risk"] in ("low", "medium", "high")
    assert all({"feature", "value", "effect"} <= set(f) for f in p1["factors"]) and "synthetic" in p1["trained_on"]


def test_calibration_error_and_risk_labels():
    assert need_model.ece([1, 1, 0, 0], [1.0, 1.0, 0.0, 0.0]) == 0.0 and need_model.ece([1, 1, 1, 1], [0.1, 0.1, 0.1, 0.1]) == pytest.approx(0.9)
    assert [need_model.risk_label(p) for p in (0.9, 0.5, 0.1)] == ["low", "medium", "high"]


# ----------------------------------------------------------------------------- forecasting
def test_backtest_compares_methods_on_the_same_origins_and_skips_arima_when_too_short():
    rising = [float(i) for i in range(1, 25)]
    bt = fm.backtest(rising)
    assert set(bt) == {"naive", "moving average (3)", "holt (damped trend)", "arima"} and len({v["n"] for v in bt.values()}) == 1
    assert bt["holt (damped trend)"]["mae"] < bt["moving average (3)"]["mae"]       # a trend is not an average
    assert "arima" not in fm.backtest([3, 4, 5, 4, 6, 5, 7, 6])
    assert fm.backtest([1.0, 2.0]) == {}


def test_forecast_picks_the_best_method_but_never_one_worse_than_naive():
    out = fm.forecast_series([float(i) for i in range(1, 25)])
    assert out["confident"] and out["forecast"] > 20 and out["mae"] <= out["naive_mae"] and out["skill_vs_naive"] >= 0
    flat = fm.forecast_series([5.0] * 12)
    assert flat["method"] == "naive" and flat["forecast"] == 5.0
    short = fm.forecast_series([2.0, 3.0, 4.0])
    assert short["confident"] is False and "fewer than 6" in short["reason"] and fm.forecast_series([])["forecast"] == 0.0
    bench = fm.benchmark(8, 20)
    assert set(bench["mean_mae"]) == {"naive", "moving average (3)", "holt (damped trend)", "arima"} and sum(bench["wins"].values()) == 8


# ----------------------------------------------------------------------------- anomaly detection and clustering
def test_isolation_forest_finds_injected_anomalies_better_than_the_rules():
    rep = am.evaluate_anomaly(800)
    iso, rules = rep["methods"]["isolation forest"], rep["methods"]["existing rules"]
    assert iso["precision_at_k"] >= 0.85 and iso["auc"] > rules["auc"]
    scored = am.isolation_scores(am.synthetic_donations(400))
    top = scored.sort_values("anomaly_score", ascending=False).head(3)
    assert top["anomaly_score"].between(0, 1).all() and any(top["reasons"].map(len))
    assert (am.isolation_scores(scored.head(5))["anomaly_score"] == 0).all()   # too few rows: no verdict


def test_donor_segments_and_need_clusters_and_similar_needs(db):
    now = datetime(2026, 6, 30)
    rng = np.random.default_rng(2)
    org = m.Organization(name="Hope", contact="c", verified=True)
    db.add(org)
    db.flush()
    needs = [m.Need(org_id=org.id, category=c, quantity=int(q), urgency=u, status="open", created_at=now - timedelta(days=int(a)))
             for c, q, u, a in [("Books", 20 + i, "high", 5 + i) for i in range(6)] + [("Food", 60 + i, "medium", 9 + i) for i in range(6)] + [("Surgery", 900, "critical", 1)]]
    db.add_all(needs)
    for i in range(12):
        d = m.Donor(name=f"D{i}", contact="x", preferences="education")
        db.add(d)
        db.flush()
        for j in range(1 + (i % 4) * 2):
            db.add(m.Donation(donor_id=d.id, need_id=needs[0].id, amount=float(rng.integers(100, 400) * (6 if i > 8 else 1)), timestamp=now - timedelta(days=int(10 + i * 25 + j))))
    db.commit()
    seg = am.donor_segments(db, now)
    assert seg["k"] >= 2 and sum(s["donors"] for s in seg["segments"]) == 12 and {s["name"] for s in seg["segments"]} <= {"Lapsed", "High value", "Loyal", "New or occasional"}
    cl = am.cluster_needs(db, now)
    assert cl["clusters"] and any(o["category"] == "Surgery" for o in cl["outliers"])    # the one huge, critical, unique need is an outlier
    sim = am.similar_needs(db, needs[1], k=3, now=now)
    assert len(sim) == 3 and all(s["category"] == "Books" for s in sim) and sim[0]["distance"] <= sim[-1]["distance"]


# ----------------------------------------------------------------------------- learning to rank
def test_learned_rankers_beat_the_hand_weighted_score_on_nonlinear_usefulness():
    X, y, g = ranker.synthetic_groups(300)
    rep = ranker.compare(X, y, g)
    base = [r for r in rep["table"] if r["model"].startswith("weighted")][0]["ndcg@3"]
    best = rep["table"][0]
    assert best["model"] != "weighted score (baseline)" and best["ndcg@3"] > base
    assert rep["test_groups"] == 75 and 0 < base < 1
    tuned = ranker.tune_weights(X[:800], y[:800], g[:800], n_iter=4)
    assert len(tuned["weights"]) == 6 and abs(sum(tuned["weights"]) - 1) < 0.01


def test_ranking_from_decisions_needs_enough_judged_needs(db):
    assert ranker.from_db(db, "donor") == {"enough": False, "groups": 0, "needed": ranker.MIN_GROUPS}
    pr = ranker.PairwiseRanker().fit(*ranker.synthetic_groups(40))
    assert pr.score(np.ones((2, 6))).shape == (2,)


# ----------------------------------------------------------------------------- Bayesian network and Monte Carlo
def test_bayesian_network_answers_do_style_questions():
    bn = bayes_net.NeedBayesNet().fit(dataset.synthetic(1500))
    assert 0 < bn.p_fulfilled() < 1 and bn.p_fulfilled(urgency=3) > bn.p_fulfilled(urgency=0)
    eff = bn.do_effect("stock_cover", urgency=3, donor_cover=1)
    assert eff["with"] > eff["without"] and eff["effect"] == pytest.approx(eff["with"] - eff["without"], abs=1e-3)
    assert bn.p_fulfilled(urgency=2, donor_cover=1, stock_cover=1) == pytest.approx(bn.cpt[(2, 1, 1)])


def test_monte_carlo_is_reproducible_and_responds_sensibly_to_inputs():
    a = simulate.simulate_supply(100, 25, 60, 40)
    assert a == simulate.simulate_supply(100, 25, 60, 40) and 0 < a["p_shortfall"] < 1 and a["unmet_p10"] <= a["unmet_p50"] <= a["unmet_p90"]
    table = simulate.compare_allocation(100, 25, 60, [10, 30, 60], pledged_units=40)
    assert [r["p_shortfall"] for r in table] == sorted([r["p_shortfall"] for r in table], reverse=True)    # more supply, less risk
    assert simulate.simulate_supply(0, 0, 10)["p_shortfall"] == 0.0 and simulate.simulate_supply(50, 5, 500)["p_shortfall"] == 0.0
    assert simulate.simulate_supply(100, 10, 0, 0)["p_shortfall"] > 0.99
    lo, hi = simulate.beta_from_rate(2, 10), simulate.beta_from_rate(9, 10)
    assert lo[0] / sum(lo) < hi[0] / sum(hi)
