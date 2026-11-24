# CareBridge AI: architecture and results

**Principle.** RAG retrieves knowledge. Machine learning predicts outcomes. Python calculates values. Optimisation algorithms make constrained decisions. A language model only explains the results. Consequential decisions are proposals that a person approves.

Run everything and regenerate the outputs: `python scripts/run_ai_pipeline.py` (about two minutes; writes `reports/ai/`: `report.md`, `metrics.json`, `agent_transcripts.md` and five charts). In the app: **Administration > AI Lab**.

## The five phases (code in `app/ai/`)
| Phase | What it does | Code | Tests |
|---|---|---|---|
| 1 Reliable data | Checks relationships, impossible values, inventory arithmetic (`available = total - approved - delivered`), over-allocation, duplicates, flag consistency and that scoring rules stay in range; safe one-click repairs | `data_quality.py` | `test_ai_data_quality.py` |
| 2 High-quality RAG | Adaptive routing, query decomposition, metadata filters, BM25 + character n-grams + dense vectors, reciprocal-rank fusion, GraphRAG ranker, cross-encoder rerank hook, corrective retrieval, cited answers with self-checks | `rag/`, `services/rag_hybrid.py` | `test_ai_rag_advanced.py`, `test_rag_v3.py` |
| 3 Predictive ML | ONE problem: *will a need be fulfilled within 14 days?* Baseline first, seven models compared, Bayesian-optimised boosting, held-out evaluation, significance guard | `ml/` | `test_ai_ml.py` |
| 4 Optimisation | Resource allocation (LP/MILP with inventory, demand, urgency, fairness and organization-share constraints), donor matching (MILP), GA, PSO, Dijkstra, A*, VRP | `optim/` | `test_ai_optimization.py` |
| 5 Agentic AI | Router, planner, retriever, analyst, optimizer, verifier and explainer; 12 typed tools; validated outputs; human approval | `agent/` | `test_ai_agent.py` |

## Which of your listed algorithms are implemented
| Implemented and tested | Notes |
|---|---|
| Hybrid search (BM25 + vectors), RRF, semantic / dense retrieval | Dense vectors use sentence-transformers when installed. **Not measurable in the build environment**, so the reported accuracy is without them. |
| Cross-encoder reranking | Loader + hook, tested with a stand-in scorer. The real model could not be downloaded here; a feature-based reranker is the fallback. |
| GraphRAG | Lightweight: a rule-based concept graph with personalised PageRank, plus a live graph over organizations / needs / categories / donors. No LLM entity extraction or community summaries. |
| Query decomposition, Adaptive RAG, Corrective RAG, Self-RAG, Agentic RAG, multi-agent orchestration | Rule-based and deterministic, with optional LLM planner / decomposer / explainer whose output is validated. Self-RAG here means support, citation and number verification, not trained reflection tokens. CRAG has no web-search fallback. The "agents" are roles inside one process. |
| XGBoost, Random Forest, Gradient Boosting, Logistic Regression, Linear Regression, SVM, KNN | Compared on the one prediction problem; linear regression on days-to-fulfil. |
| Isolation Forest, K-Means, DBSCAN | Donation anomalies, donor segments, outlier needs; KNN for similar past needs. |
| Time-series forecasting, ARIMA | Rolling-origin backtests against naive, moving average and damped-trend smoothing. |
| Learning to rank | Pairwise (RankNet-style) and XGBoost LambdaMART. |
| Bayesian optimisation, Bayesian network, Monte Carlo | Custom GP + Expected Improvement; a small discrete network with exact inference; shortfall simulation. |
| Weighted scoring | The existing donor / volunteer / resource scores; weights can be tuned with Bayesian optimisation. |
| LP, MILP, Genetic Algorithm, PSO, Dijkstra, A*, VRP | MILP is the production solver; GA and PSO are comparisons; VRP is the Clarke-Wright savings heuristic with 2-opt (not an exact optimum). |
| **Not implemented: LSTM** | Needs PyTorch or TensorFlow (not installed) and thousands of points per series; a child-welfare platform has a few dozen monthly values. ARIMA and Holt are the right size. |
| Transformer-based models | Only through the optional sentence-transformers / cross-encoder; not run here. |

## Results (reproduce with the script; numbers below are from the run in `reports/ai/`)
Benchmarks marked *synthetic* use generated data with a known process. They measure the **methods**, not CareBridge's real-world accuracy.

* **Phase 1.** The demo database is clean (0 errors). After injecting faults the check found 4 errors and 1 warning (`donation_donor`, `donation_need`, `donation_value`, `duplicate_needs`, `resource_stock`); one-click repair fixed the inventory.
* **Phase 2, retrieval (top-3 / off-topic refused).** Keyword TF-IDF baseline: development 72%, held-out 47%, fresh 36%, and it refused only 14 of 37 off-topic questions. Hybrid retrieval: 96%, 96%, **59%**, refusing 37 of 37. Adding the graph and corrective steps changed nothing measurable. The *fresh* set (paraphrases written after tuning) is the realistic one; dense vectors and a cross-encoder are the expected next gain and are unverified here.
* **Phase 3, need fulfilment (synthetic, 1,500 needs, 300 held out).** Logistic regression won: cross-validated AUC 0.735, held-out AUC 0.699 (95% interval 0.63 to 0.76) against the baseline's 0.558 (0.48 to 0.63). The best possible score on this data is 0.724. XGBoost 0.676, random forest 0.671, gradient boosting 0.662, SVM 0.633, KNN 0.617. The data's one interaction effect was too weak for boosted trees to beat the simple model, so start simple. Days-to-fulfil regression barely beats predicting the mean (6.62 vs 6.75 days).
  On the 176-need *demo database* the baseline stayed in charge, which is correct because that data is generated from urgency alone; a noisy cross-validation edge is not accepted (corrected paired test, see `need_model.py`).
* **Forecasting (30 synthetic series).** The naive forecast had the lowest mean backtest error (1.89) and won 22 series; ARIMA 1.96, damped trend 2.07, moving average 2.35. The system picks the best method per category but never one worse than naive.
* **Anomaly detection (synthetic, injected anomalies).** Isolation Forest precision-at-k 0.98 vs the existing rules 0.79 (this is optimistic: it was given the true anomaly rate).
* **Learning to rank (synthetic, NDCG@3).** XGBoost LambdaMART 0.874, pairwise logistic 0.873, hand-weighted baseline 0.850.
* **Phase 4 (synthetic instance, scarce stock).** Max-min MILP lifts the worst-served need from 0% to 45% coverage (fairness index 0.63 to 0.93) while giving out the same 174 units, at 87% of the greedy plan's utility. MILP equals the LP upper bound on pure utility; greedy reaches 95.7%, PSO 95.6%, GA 91.6%. GA and PSO with a fairness penalty still left the worst-served need at 0%. Donor matching covers 14 of 14 needs (greedy 13). VRP: 77.8 km vs 87.3 km for nearest-neighbour. An independent checker found no constraint violations.
* **Phase 5.** All 8 sample agent runs passed every verifier check (structured output, citations, constraints, numbers grounded); optimiser answers were labelled as proposals.

## Safety design
* Every tool has a typed input and a validated output; invalid output is rejected.
* The language model may only use numbers present in tool results; otherwise the template explanation is used.
* `optimize_allocation` and `optimize_matching` only create `proposed` / `suggested` rows when an administrator ticks "create proposals"; stock is untouched until a person approves in the review queue.
* Non-administrators get only the two knowledge tools. Every run and every proposal batch is in the audit trail.

## Limits to know
* The prediction model trains on real data only after 80 labelled needs (12 of each outcome); until then a transparent baseline is used. Record `fulfilled_at` (set automatically when a need becomes fulfilled).
* Routing needs latitude / longitude on organizations and needs (new optional fields).
* The retrieval question sets are written by the developers. Real accuracy needs real user questions: use the assistant's "questions it could not answer" list.
