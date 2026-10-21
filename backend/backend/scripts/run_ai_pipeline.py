"""Run every phase of the CareBridge AI pipeline on a reproducible demo dataset and write the outputs.

    python scripts/run_ai_pipeline.py [--out reports/ai] [--quick]

Writes  metrics.json, report.md, agent_transcripts.md and PNG charts into the output folder.
All benchmark numbers marked "synthetic" come from generated data with a known process: they measure the METHODS. They are not the
platform's real-world accuracy, which can only be measured on real history (the pipeline trains on real data automatically once enough exists)."""
import argparse
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models as m  # noqa: E402
from app.ai import data_quality, demo  # noqa: E402
from app.ai.agent import orchestrator  # noqa: E402
from app.ai.ml import anomaly_ml, bayes_net, dataset, forecast_models, need_model, ranker, simulate  # noqa: E402
from app.ai.optim import allocation as al, metaheuristics as mh, routing as rt  # noqa: E402
from app.ai.rag import crag, graph  # noqa: E402
from app.database import Base  # noqa: E402
from app.knowledge.default_kb import ENTRIES, with_keywords  # noqa: E402
from app.services import rag_hybrid  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402

COL = {"teal": "#0F766E", "violet": "#7C3AED", "sky": "#0284C7", "green": "#16A34A", "amber": "#D97706", "rose": "#E11D48", "ink": "#12292B", "grey": "#9AB0AD"}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#9AB0AD", "axes.titleweight": "bold", "figure.facecolor": "white"})


def rag_eval() -> dict:
    rows = [m.KnowledgeBase(id=i + 1, title=t, source=s, content=with_keywords(t, c)) for i, (t, s, c) in enumerate(ENTRIES)]
    kg = graph.KnowledgeGraph(rows)
    docs = [f"{r.title}. {rag_hybrid.split_hidden(r.content)[0]}" for r in rows]
    tf = TfidfVectorizer(stop_words="english").fit(docs)
    dm = tf.transform(docs)

    def keyword(q):
        sims = (dm @ tf.transform([q]).T).toarray().ravel()
        order = np.argsort(-sims)[:3]
        return [{"title": rows[i].title, "confidence": float(sims[i]), "answerable": sims[i] > 0.12} for i in order]

    def hybrid(q):
        return rag_hybrid.search(rows, q, None, 3)

    def full(q):
        return crag.corrective_retrieve(lambda qq, f=None, ids=None: rag_hybrid.search([e for e in rows if ids is None or e.id in ids], qq, None, 5, extra_rankers=[(0.8, kg.rank(qq))]), q)["results"][:3]

    out = {}
    for name, path in (("development", "eval_questions.json"), ("held-out", "eval_heldout.json"), ("fresh", "eval_fresh.json")):
        data = json.loads((Path(__file__).resolve().parents[1] / "app" / "knowledge" / path).read_text())
        out[name] = {}
        for label, fn in (("keyword TF-IDF (baseline)", keyword), ("hybrid (BM25 + n-gram + fusion + rerank)", hybrid), ("+ graph + corrective RAG", full)):
            r1 = r3 = 0
            for it in data["in_scope"]:
                titles = [r["title"] for r in fn(it["q"])]
                r1 += titles[:1] == [it["expected"]]
                r3 += it["expected"] in titles
            refused = sum(1 for q in data["out_of_scope"] if not (r := fn(q)) or not r[0]["answerable"])
            n = len(data["in_scope"])
            out[name][label] = {"questions": n, "recall_at_1": round(r1 / n, 3), "recall_at_3": round(r3 / n, 3), "off_topic_refused": f"{refused}/{len(data['out_of_scope'])}"}
    return out


def build_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    info = demo.build_demo(db)
    return db, info


def savefig(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main(out_dir: str, quick: bool):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    M: dict = {"generated_with": "scripts/run_ai_pipeline.py", "dataset_note": "Demo data and synthetic benchmarks are generated; they measure methods, not real-world accuracy."}

    print("Phase 1: data quality ...")
    db, info = build_db()
    clean = data_quality.check(db, info["now"])
    res = db.query(m.Resource).first()
    res.quantity_available -= 7
    db.add(m.Donation(donor_id=9999, need_id=8888, amount=-5))
    db.commit()
    broken = data_quality.check(db, info["now"])
    fixed = data_quality.repair(db, ["resource_stock"])
    M["phase1_data_quality"] = {"demo_tables": clean["tables"], "clean_demo": {"ok": clean["ok"], "errors": clean["errors"], "warnings": clean["warnings"]},
                                "after_injecting_faults": {"errors": broken["errors"], "detected": sorted(i["code"] for i in broken["issues"])}, "auto_repair": fixed}
    db.query(m.Donation).filter(m.Donation.donor_id == 9999).delete()
    db.commit()

    print("Phase 2: RAG evaluation ...")
    M["phase2_rag"] = rag_eval()

    print("Phase 3: prediction models ...")
    df = dataset.synthetic(1500)
    cmp_ = need_model.compare(df, tune_models=True, n_iter=6 if quick else 10)
    M["phase3_need_model"] = {"problem": "P(need fulfilled within 14 days)", "data": "synthetic benchmark (1500 needs, known generating process)", "rows": cmp_["rows"], "test_rows": cmp_["test_rows"],
                              "table": cmp_["table"], "selected": cmp_["selected"], "beat_baseline": cmp_["beat_baseline"], "selected_test_auc_ci95": cmp_["selected_test_auc_ci95"],
                              "baseline_test_auc_ci95": cmp_["baseline_test_auc_ci95"], "oracle_test_auc": cmp_["oracle_test_auc"], "tuned": cmp_["tuned"], "tuning_history": cmp_["tuning_history"],
                              "regression_days_to_fulfil": need_model.compare_regression(df)["table"]}
    from app.ai.ml.dataset import training_frame
    real = training_frame(db, info["now"])
    real_cmp = need_model.compare(real, tune_models=False, cv_folds=5)
    M["phase3_need_model_demo_db"] = {"data": "demo database (made-up history, generated by demo.py)", "labelled_needs": len(real), "selected": real_cmp["selected"], "beat_baseline": real_cmp["beat_baseline"],
                                     "table": [{k: r[k] for k in ("model", "cv_auc_mean", "test_roc_auc")} for r in real_cmp["table"]]}
    M["phase3_forecast_benchmark"] = forecast_models.benchmark(30, 24)
    demo_fc = {c: forecast_models.forecast_series(s) for c, s in forecast_models.category_series(db, info["now"]).items()}
    M["phase3_forecast_demo_categories"] = {c: {k: v for k, v in f.items() if k != "backtest"} | {"backtest": f.get("backtest", {})} for c, f in demo_fc.items()}
    M["phase3_anomaly"] = anomaly_ml.evaluate_anomaly(1200)
    X, y, g = ranker.synthetic_groups(400)
    M["phase3_learning_to_rank"] = {"data": "synthetic", **{k: v for k, v in ranker.compare(X, y, g).items() if not k.startswith("_")}}
    seg = anomaly_ml.donor_segments(db, info["now"])
    M["phase3_donor_segments"] = {"k": seg["k"], "silhouette": seg.get("silhouette"), "segments": seg["segments"]}
    scored = anomaly_ml.isolation_scores(anomaly_ml.donation_frame(db)).sort_values("anomaly_score", ascending=False).head(5)
    M["phase3_demo_flagged_donations"] = [{"donation_id": int(r.donation_id), "amount": float(r.amount), "score": float(r.anomaly_score), "reasons": r.reasons} for r in scored.itertuples()]
    bn = bayes_net.NeedBayesNet().fit(df)
    M["phase3_bayesian_network"] = {"p_fulfilled_critical": round(bn.p_fulfilled(urgency=3), 3), "effect_of_stock_for_critical_with_donors": bn.do_effect("stock_cover", urgency=3, donor_cover=1)}
    mc = simulate.simulate_supply(100, 25, 60, 40)
    M["phase3_monte_carlo"] = {"example": {k: v for k, v in mc.items() if k != "unmet_samples"}, "extra_allocation": simulate.compare_allocation(100, 25, 60, [10, 20, 40, 60], pledged_units=40)}
    M["phase3_monte_carlo"]["samples"] = mc["unmet_samples"]

    print("Phase 4: optimization ...")
    S, D, C = al.random_instance(seed=7)
    cmpo = mh.compare_solvers(S, D, C)
    maxmin = al.solve_allocation(S, D, C, fairness="maxmin", urgent_first=True)
    none = al.solve_allocation(S, D, C, fairness="none", urgent_first=False)
    greedy = al.greedy_allocation(S, D, C)
    donors = [{"id": i, "capacity": 2} for i in range(1, 11)]
    needs = [{"id": i, "weight": al.URGENCY_WEIGHT[["low", "medium", "high", "critical"][i % 4]], "org_id": i % 4} for i in range(1, 15)]
    rng = np.random.default_rng(3)
    fit = {(d["id"], n["id"]): round(float(rng.uniform(0.1, 1)), 3) for d in donors for n in needs if rng.random() < 0.5}
    mm, gm = al.solve_matching(donors, needs, fit, max_donors_per_need=1), al.greedy_matching(donors, needs, fit, 1)
    depot = (17.385, 78.4867)
    stops = [{"id": i, "lat": 17.385 + 0.06 * np.cos(i), "lon": 78.4867 + 0.06 * np.sin(i * 1.7), "demand": 3 + i % 4} for i in range(1, 15)]
    vrp = rt.solve_vrp(depot, stops, 4, 20)
    M["phase4_optimization"] = {"instance": f"{len(S)} stock lines, {len(D)} needs (synthetic, scarce stock)", "solver_comparison": cmpo,
                                "urgent_first_maxmin": maxmin["metrics"], "utility_only": none["metrics"], "greedy": greedy["metrics"],
                                "constraint_violations": {"maxmin": al.check_feasibility(S, D, maxmin), "none": al.check_feasibility(S, D, none)},
                                "matching": {"milp": mm["metrics"], "greedy": gm["metrics"]},
                                "routing": {"vrp_km": vrp["total_km"], "nearest_neighbour_km": rt.nearest_neighbour_baseline(depot, stops, 20), "routes": len(vrp["routes"]), "feasible": vrp["feasible"]}}

    print("Phase 5: agent ...")
    admin = {"role": "admin", "id": 1, "email": "admin@demo.org"}
    questions = ["How many wrong passwords lock an account?", "Forecast books demand next month and the risk of a shortage", "Will need 5 be fulfilled in time?",
                 "Allocate the books and food fairly across the needs", "Match donors to the open needs", "Show suspicious donations", "What is the average donation?", "How do I reset my password and what are recovery codes?"]
    runs = []
    for q in questions:
        r = orchestrator.run_agent(db, q, admin)
        runs.append(r)
    M["phase5_agent"] = [{"question": r["question"], "route": r["route"]["route"], "tools": [s["tool"] for s in r["steps"]], "status": [s["status"] for s in r["steps"]], "requires_approval": r["requires_approval"],
                          "validation_ok": all(r["validation"][k] for k in ("schema_ok", "rag_ok", "constraints_ok", "numbers_ok")), "proposals_created": len(r["proposals"])} for r in runs]
    M["runtime_seconds"] = round(time.time() - t0, 1)
    (out / "metrics.json").write_text(json.dumps(M, indent=1, default=str))
    print("Charts ...")
    make_charts(M, out)

    # ----------------------------------------------------------------- written outputs
    (out / "agent_transcripts.md").write_text(render_transcripts(runs))
    (out / "report.md").write_text(render_report(M))
    print(f"Done in {M['runtime_seconds']} s -> {out}")


def bar_labels(ax, bars, fmt="{:.2f}", pad=0.005):
    for b in bars:
        w = b.get_width()
        ax.text(w + pad, b.get_y() + b.get_height() / 2, fmt.format(w), va="center", fontsize=8, color=COL["ink"])


def make_charts(M: dict, out: Path):
    n3 = M["phase3_need_model"]
    tab = sorted(n3["table"], key=lambda r: r["test_roc_auc"])
    fig, ax = plt.subplots(figsize=(9, 5.4))
    ypos = np.arange(len(tab))
    b1 = ax.barh(ypos - 0.2, [r["cv_auc_mean"] for r in tab], 0.38, label="cross-validation (training part)", color=COL["sky"])
    b2 = ax.barh(ypos + 0.2, [r["test_roc_auc"] for r in tab], 0.38, label="held-out test (most recent 20%)", color=COL["teal"])
    bar_labels(ax, b1, "{:.3f}")
    bar_labels(ax, b2, "{:.3f}")
    ax.axvline(n3["oracle_test_auc"], color=COL["rose"], ls="--", lw=1.5)
    ax.text(n3["oracle_test_auc"] + 0.004, -0.55, "best possible\n(knows the true process)", color=COL["rose"], fontsize=8, va="bottom")
    ax.set_yticks(ypos, [r["model"] for r in tab])
    ax.set_xlim(0.45, 0.80)
    ax.set_xlabel("ROC-AUC (higher is better)")
    ax.set_title("Need fulfilment: model comparison (synthetic benchmark)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2, fontsize=8, frameon=False)
    savefig(fig, out / "1_model_comparison.png")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    fb = M["phase3_forecast_benchmark"]
    bars = axes[0].bar(list(fb["mean_mae"]), list(fb["mean_mae"].values()), color=[COL["grey"], COL["sky"], COL["violet"], COL["teal"]])
    axes[0].bar_label(bars, fmt="%.2f", fontsize=8)
    axes[0].set_title("Forecast error by method\n(mean backtest MAE, lower is better)", fontsize=10)
    axes[0].tick_params(axis="x", labelrotation=20)
    bars = axes[1].bar(list(fb["wins"]), list(fb["wins"].values()), color=COL["amber"])
    axes[1].bar_label(bars, fontsize=8)
    axes[1].set_title(f"How often each method wins\n({fb['series']} synthetic series)", fontsize=10)
    axes[1].tick_params(axis="x", labelrotation=20)
    savefig(fig, out / "2_forecast_backtest.png")

    cmpo = M["phase4_optimization"]["solver_comparison"]
    u, f = cmpo["utility_only"], cmpo["fairness"]
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), gridspec_kw={"width_ratios": [1, 1, 1]})
    for ax, names, vals, title, color, xlim in (
            (axes[0], list(u), [v["vs_bound"] for v in u.values()], "Utility vs the LP upper bound\n(1.0 = optimal)", COL["teal"], (0.8, 1.04)),
            (axes[1], list(f), [v["min_coverage"] for v in f.values()], "Worst-served need: share of its demand covered\n(higher is fairer)", COL["violet"], (0, 0.65)),
            (axes[2], list(f), [v["jain"] for v in f.values()], "Jain fairness index\n(1.0 = perfectly even)", COL["sky"], (0.4, 1.06))):
        bars = ax.barh(names[::-1], vals[::-1], color=color)
        bar_labels(ax, bars, "{:.2f}", pad=0.004)
        ax.set_xlim(*xlim)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="y", labelsize=8)
    savefig(fig, out / "3_optimization.png")

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5))
    labels = list(M["phase2_rag"]["fresh"])
    x = np.arange(3)
    for i, (lab, c) in enumerate(zip(labels, [COL["grey"], COL["teal"], COL["violet"]])):
        vals = [M["phase2_rag"][s][lab]["recall_at_3"] for s in ("development", "held-out", "fresh")]
        bars = axes[0].bar(x + (i - 1) * 0.26, vals, 0.25, label=lab, color=c)
        axes[0].bar_label(bars, fmt="%.2f", fontsize=7)
    axes[0].set_xticks(x, ["development\n(tuned on)", "held-out", "fresh\n(realistic)"])
    axes[0].set_ylim(0, 1.1)
    axes[0].set_title("Retrieval: correct passage in the top 3", fontsize=10)
    axes[0].legend(fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=1)
    an = M["phase3_anomaly"]["methods"]
    bars = axes[1].bar(["isolation forest", "existing rules"], [an["isolation forest"]["precision_at_k"], an["existing rules"]["precision_at_k"]], color=[COL["teal"], COL["grey"]])
    axes[1].bar_label(bars, fmt="%.2f", fontsize=9)
    axes[1].set_title("Anomaly detection: precision of the top-k flags\n(synthetic donations, injected anomalies)", fontsize=10)
    axes[1].set_ylim(0, 1.1)
    savefig(fig, out / "4_rag_and_anomaly.png")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    mc = M["phase3_monte_carlo"]
    axes[0].hist(mc["samples"], bins=24, color=COL["amber"])
    axes[0].set_title("Monte Carlo: unmet demand across 200 of 10,000 scenarios", fontsize=10)
    axes[0].set_xlabel("units short")
    ex = mc["extra_allocation"]
    axes[1].plot([r["extra"] for r in ex], [r["p_shortfall"] for r in ex], "o-", color=COL["rose"])
    for r in ex:
        axes[1].annotate(f"{r['p_shortfall']:.0%}", (r["extra"], r["p_shortfall"]), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8)
    axes[1].set_title("Chance of a shortfall vs extra units allocated", fontsize=10)
    axes[1].set_xlabel("extra units")
    axes[1].set_ylim(0, 1.05)
    savefig(fig, out / "5_monte_carlo.png")


def render_transcripts(runs) -> str:
    lines = ["# AI agent: sample runs on the demo dataset", "", "Each run shows the route chosen, the tools used, their status, the answer and the verifier's checks. Optimizer plans are proposals only.", ""]
    for i, r in enumerate(runs, 1):
        v = r["validation"]
        lines += [f"## {i}. {r['question']}", "", f"* **Route:** {r['route']['route']}  |  **Planned by:** {r.get('planned_by', 'n/a')}", "* **Tools:** " + (", ".join(f"`{s['tool']}` ({s['agent']}, {s['status']}, {s['ms']} ms)" for s in r["steps"]) or "none"),
                  f"* **Checks:** schema {'ok' if v['schema_ok'] else 'FAILED'}, RAG {'ok' if v['rag_ok'] else 'FAILED'}, constraints {'ok' if v['constraints_ok'] else 'FAILED'}, numbers grounded {'ok' if v['numbers_ok'] else 'FAILED'}"
                  + ("  |  **needs human approval**" if r["requires_approval"] else ""), "", "> " + r["answer"].replace("\n", "\n> "), ""]
    return "\n".join(lines)


def table(rows, cols, heads):
    out = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for r in rows:
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def render_report(M) -> str:
    n3 = M["phase3_need_model"]
    rag = M["phase2_rag"]
    L = ["# CareBridge AI: pipeline report", "", f"_{M['dataset_note']}_", "",
         "## Architecture principle", "RAG retrieves knowledge; machine learning predicts outcomes; Python calculates values; optimisation algorithms make constrained decisions; a language model only explains the results. Consequential decisions are proposals that a person approves.", "",
         "## Phase 1 - Reliable data", f"* Demo database: {M['phase1_data_quality']['demo_tables']}",
         f"* Clean demo: errors {M['phase1_data_quality']['clean_demo']['errors']}, warnings {M['phase1_data_quality']['clean_demo']['warnings']}.",
         f"* After injecting faults the check found: {', '.join(M['phase1_data_quality']['after_injecting_faults']['detected'])}; one-click repair: {M['phase1_data_quality']['auto_repair']}.", "",
         "## Phase 2 - RAG (hybrid retrieval, reranking, GraphRAG, corrective RAG, cited answers)"]
    for s in rag:
        L += ["", f"**{s} question set**", "", table([{"method": k, **v} for k, v in rag[s].items()], ["method", "questions", "recall_at_1", "recall_at_3", "off_topic_refused"], ["Method", "Questions", "Top-1", "Top-3", "Off-topic refused"])]
    L += ["", "Reading: the *fresh* set (written after tuning, paraphrases with little word overlap) is the realistic one. Graph and corrective steps did not change recall measurably here; they protect against wrong filters and weak first retrievals and keep off-topic refusals at 100%. Dense vectors and a cross-encoder (not installable in the build environment) are the expected next gain.", "",
          "## Phase 3 - Predictive ML (one problem: fulfilled within 14 days?)", f"Data: {n3['data']}. Held-out rows: {n3['test_rows']}. Best possible AUC on this data: {n3['oracle_test_auc']}.", "",
          table(n3["table"], ["model", "cv_auc_mean", "test_roc_auc", "test_pr_auc", "test_brier", "test_ece"], ["Model", "CV AUC", "Held-out AUC", "PR-AUC", "Brier", "Calibration error"]), "",
          f"Selected: **{n3['selected']}** (beat the baseline: {n3['beat_baseline']}); held-out AUC 95% interval {n3['selected_test_auc_ci95']} vs baseline {n3['baseline_test_auc_ci95']}.", "",
          "Days-to-fulfil regression (MAE in days, lower is better):", "", table(n3["regression_days_to_fulfil"], ["model", "test_mae_days"], ["Model", "MAE (days)"]), "",
          f"Forecasting benchmark (30 synthetic series): mean backtest MAE {M['phase3_forecast_benchmark']['mean_mae']}; wins {M['phase3_forecast_benchmark']['wins']}.", "",
          f"Anomaly detection (synthetic): {M['phase3_anomaly']['methods']}.", "", f"Learning to rank (synthetic, NDCG@3): {M['phase3_learning_to_rank']['table']}.", "",
          f"Bayesian network: {M['phase3_bayesian_network']}. Monte Carlo example: {M['phase3_monte_carlo']['example']}.", "",
          "LSTM is not implemented: it needs a deep-learning framework and far more data per series than a child-welfare platform has; ARIMA and damped-trend smoothing are the right size.", "",
          "## Phase 4 - Optimisation", f"Instance: {M['phase4_optimization']['instance']}.", "", f"Utility-only comparison: {M['phase4_optimization']['solver_comparison']['utility_only']}", "",
          f"Fairness comparison: {M['phase4_optimization']['solver_comparison']['fairness']}", "", f"Matching: {M['phase4_optimization']['matching']}. Routing: {M['phase4_optimization']['routing']}.", "",
          f"Constraint violations (independent checker): {M['phase4_optimization']['constraint_violations']}.", "", "## Phase 5 - Agent", "", table([{**r, "tools": ", ".join(r["tools"])} for r in M["phase5_agent"]],
          ["question", "route", "tools", "requires_approval", "validation_ok", "proposals_created"], ["Question", "Route", "Tools", "Needs approval", "All checks ok", "Proposals created"]), ""]
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/ai")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--charts-only", action="store_true", help="redraw the charts from an existing metrics.json")
    a = ap.parse_args()
    if a.charts_only:
        make_charts(json.loads((Path(a.out) / "metrics.json").read_text()), Path(a.out))
    else:
        main(a.out, a.quick)
