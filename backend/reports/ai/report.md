# CareBridge AI: pipeline report

_Demo data and synthetic benchmarks are generated; they measure methods, not real-world accuracy._

## Architecture principle
RAG retrieves knowledge; machine learning predicts outcomes; Python calculates values; optimisation algorithms make constrained decisions; a language model only explains the results. Consequential decisions are proposals that a person approves.

## Phase 1 - Reliable data
* Demo database: {'organizations': 5, 'needs': 184, 'donors': 25, 'volunteers': 15, 'donations': 126, 'resources': 6, 'allocations': 0, 'users': 0}
* Clean demo: errors 0, warnings 1.
* After injecting faults the check found: donation_donor, donation_need, donation_value, duplicate_needs, resource_stock; one-click repair: {'resource_stock': 1}.

## Phase 2 - RAG (hybrid retrieval, reranking, GraphRAG, corrective RAG, cited answers)

**development question set**

| Method | Questions | Top-1 | Top-3 | Off-topic refused |
|---|---|---|---|---|
| keyword TF-IDF (baseline) | 99 | 0.475 | 0.717 | 7/15 |
| hybrid (BM25 + n-gram + fusion + rerank) | 99 | 0.859 | 0.96 | 15/15 |
| + graph + corrective RAG | 99 | 0.869 | 0.96 | 15/15 |

**held-out question set**

| Method | Questions | Top-1 | Top-3 | Off-topic refused |
|---|---|---|---|---|
| keyword TF-IDF (baseline) | 47 | 0.277 | 0.468 | 4/12 |
| hybrid (BM25 + n-gram + fusion + rerank) | 47 | 0.872 | 0.957 | 12/12 |
| + graph + corrective RAG | 47 | 0.872 | 0.957 | 12/12 |

**fresh question set**

| Method | Questions | Top-1 | Top-3 | Off-topic refused |
|---|---|---|---|---|
| keyword TF-IDF (baseline) | 44 | 0.182 | 0.364 | 3/10 |
| hybrid (BM25 + n-gram + fusion + rerank) | 44 | 0.432 | 0.591 | 10/10 |
| + graph + corrective RAG | 44 | 0.432 | 0.591 | 10/10 |

Reading: the *fresh* set (written after tuning, paraphrases with little word overlap) is the realistic one. Graph and corrective steps did not change recall measurably here; they protect against wrong filters and weak first retrievals and keep off-topic refusals at 100%. Dense vectors and a cross-encoder (not installable in the build environment) are the expected next gain.

## Phase 3 - Predictive ML (one problem: fulfilled within 14 days?)
Data: synthetic benchmark (1500 needs, known generating process). Held-out rows: 300. Best possible AUC on this data: 0.724.

| Model | CV AUC | Held-out AUC | PR-AUC | Brier | Calibration error |
|---|---|---|---|---|---|
| logistic regression | 0.7347 | 0.6992 | 0.8536 | 0.1775 | 0.0486 |
| xgboost | 0.7177 | 0.6765 | 0.8382 | 0.1809 | 0.0512 |
| gradient boosting | 0.7053 | 0.6619 | 0.8334 | 0.1843 | 0.0473 |
| random forest | 0.6997 | 0.6713 | 0.8174 | 0.183 | 0.0561 |
| k-nearest neighbours | 0.6738 | 0.617 | 0.7956 | 0.1935 | 0.0603 |
| svm (rbf) | 0.6676 | 0.6331 | 0.7898 | 0.1889 | 0.0339 |
| baseline (urgency prior) | 0.5754 | 0.5579 | 0.7505 | 0.1969 | 0.0072 |

Selected: **logistic regression** (beat the baseline: True); held-out AUC 95% interval [0.625, 0.7646] vs baseline [0.4796, 0.629].

Days-to-fulfil regression (MAE in days, lower is better):

| Model | MAE (days) |
|---|---|
| random forest | 6.62 |
| xgboost | 6.63 |
| linear regression | 6.64 |
| ridge regression | 6.64 |
| gradient boosting | 6.71 |
| mean baseline | 6.75 |

Forecasting benchmark (30 synthetic series): mean backtest MAE {'naive': 1.889, 'moving average (3)': 2.345, 'holt (damped trend)': 2.072, 'arima': 1.958}; wins {'naive': 22, 'moving average (3)': 4, 'holt (damped trend)': 2, 'arima': 2}.

Anomaly detection (synthetic): {'isolation forest': {'auc': 0.9999, 'precision_at_k': 0.9792, 'recall_at_k': 0.9792}, 'existing rules': {'auc': 0.8956, 'precision_at_k': 0.7917, 'recall_at_k': 0.7917}}.

Learning to rank (synthetic, NDCG@3): [{'model': 'xgboost lambdamart', 'ndcg@3': 0.8738}, {'model': 'pairwise logistic (RankNet-style)', 'ndcg@3': 0.8731}, {'model': 'weighted score (baseline)', 'ndcg@3': 0.8498}].

Bayesian network: {'p_fulfilled_critical': 0.786, 'effect_of_stock_for_critical_with_donors': {'with': 0.9737, 'without': 0.7763, 'effect': 0.1974}}. Monte Carlo example: {'p_shortfall': 0.6694, 'expected_unmet': 18.41, 'unmet_p10': 0.0, 'unmet_p50': 11.79, 'unmet_p90': 48.81, 'expected_demand': 99.69, 'expected_supply': 87.12, 'scenarios': 10000}.

LSTM is not implemented: it needs a deep-learning framework and far more data per series than a child-welfare platform has; ARIMA and damped-trend smoothing are the right size.

## Phase 4 - Optimisation
Instance: 8 stock lines, 14 needs (synthetic, scarce stock).

Utility-only comparison: {'lp relaxation (upper bound)': {'utility': 350.7755, 'vs_bound': 1.0}, 'milp (exact, integer)': {'utility': 350.7755, 'vs_bound': 1.0}, 'greedy': {'utility': 335.523, 'vs_bound': 0.9565}, 'genetic algorithm': {'utility': 321.2903, 'vs_bound': 0.9159}, 'particle swarm': {'utility': 335.3622, 'vs_bound': 0.9561}}

Fairness comparison: {'milp maxmin': {'utility': 258.9915, 'min_coverage': 0.5152, 'jain': 0.9951, 'gini': 0.0291}, 'milp floor (alpha 0.8)': {'utility': 307.2545, 'min_coverage': 0.4138, 'jain': 0.9057, 'gini': 0.1355}, 'milp utility only': {'utility': 350.7755, 'min_coverage': 0.0, 'jain': 0.6443, 'gini': 0.3852}, 'greedy': {'utility': 335.523, 'min_coverage': 0.0, 'jain': 0.6346, 'gini': 0.4068}, 'genetic algorithm (fairness-aware)': {'utility': 319.9133, 'min_coverage': 0.0, 'jain': 0.6838, 'gini': 0.3855}, 'particle swarm (fairness-aware)': {'utility': 338.7774, 'min_coverage': 0.0, 'jain': 0.5812, 'gini': 0.4574}}

Matching: {'milp': {'needs_covered': 14, 'needs_total': 14, 'orgs_covered': 4, 'orgs_total': 4, 'total_fit': 10.568, 'weighted_fit': 23.6935, 'max_donor_load': 2}, 'greedy': {'needs_covered': 13, 'needs_total': 14, 'orgs_covered': 4, 'total_fit': 9.759, 'weighted_fit': 22.518}}. Routing: {'vrp_km': 77.803, 'nearest_neighbour_km': 87.335, 'routes': 4, 'feasible': True}.

Constraint violations (independent checker): {'maxmin': [], 'none': []}.

## Phase 5 - Agent

| Question | Route | Tools | Needs approval | All checks ok | Proposals created |
|---|---|---|---|---|---|
| How many wrong passwords lock an account? | knowledge | retrieve_knowledge | False | True | 0 |
| Forecast books demand next month and the risk of a shortage | prediction | forecast_demand, simulate_shortfall | False | True | 0 |
| Will need 5 be fulfilled in time? | prediction | predict_fulfilment, similar_needs | False | True | 0 |
| Allocate the books and food fairly across the needs | optimization | optimize_allocation | True | True | 0 |
| Match donors to the open needs | optimization | optimize_matching | True | True | 0 |
| Show suspicious donations | anomaly | detect_anomalies | False | True | 0 |
| What is the average donation? | calculation | calculate | False | True | 0 |
| How do I reset my password and what are recovery codes? | knowledge | retrieve_knowledge | False | True | 0 |
