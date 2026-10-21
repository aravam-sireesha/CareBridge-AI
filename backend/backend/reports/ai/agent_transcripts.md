# AI agent: sample runs on the demo dataset

Each run shows the route chosen, the tools used, their status, the answer and the verifier's checks. Optimizer plans are proposals only.

## 1. How many wrong passwords lock an account?

* **Route:** knowledge  |  **Planned by:** rules
* **Tools:** `retrieve_knowledge` (retriever, ok, 30 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok

> After 5 wrong passwords or wrong two-step codes in a row the account is locked for 15 minutes and the message says how long to wait [1]. There is also a limit on how many attempts one device can make in a few minutes [1]. Too many attempts means the safety limit was reached: either the account is locked for 15 minutes after repeated wrong passwords, or one device made too many sign-in requests in a few minutes [2]. If you forgot your password use Forgot password instead of guessing [2].

## 2. Forecast books demand next month and the risk of a shortage

* **Route:** prediction  |  **Planned by:** rules
* **Tools:** `forecast_demand` (analyst, ok, 225 ms), `simulate_shortfall` (analyst, ok, 168 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok

> Next month for books: about 0.0 request(s), using arima, backtest error 1.018 versus 1.5 for the naive forecast.
> Next month for tutoring: about 0.0 request(s), using naive, backtest error 0.0 versus 0.0 for the naive forecast.
> For Books, about 0.0 units are expected against 180.0 in stock: the chance of a shortfall is 0%, with 0.0 units unmet on average.
> Adding 10 units lowers the shortfall chance to 0%.
> Adding 25 units lowers the shortfall chance to 0%.
> Adding 50 units lowers the shortfall chance to 0%.

## 3. Will need 5 be fulfilled in time?

* **Route:** prediction  |  **Planned by:** rules
* **Tools:** `predict_fulfilment` (analyst, ok, 30 ms), `similar_needs` (analyst, ok, 4 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok

> Need 5 has a 27% chance of being fulfilled within 14 days (high risk). Model: baseline (urgency prior); main factors: no model factors yet.
> Need 5 resembles need 116 (Medicine), need 77 (Medicine), need 66 (Medicine).

## 4. Allocate the books and food fairly across the needs

* **Route:** optimization  |  **Planned by:** rules
* **Tools:** `optimize_allocation` (optimizer, ok, 34 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok  |  **needs human approval**

> The allocation plan gives out 324 units and leaves 640 unmet. Worst-served need reaches 0% coverage (a greedy plan reaches 0%); fairness index 0.4679.
> Note: the worst-served need stays at zero coverage because stock is too scarce and critical needs were served first.
> It was checked against every inventory and demand limit: no violations. This is a proposal that needs human approval.

## 5. Match donors to the open needs

* **Route:** optimization  |  **Planned by:** rules
* **Tools:** `optimize_matching` (optimizer, ok, 141 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok  |  **needs human approval**

> The matching covers 43 of 43 needs (greedy covers 26) and 5 organization(s). It respects every donor's capacity. This is a proposal that needs human approval.

## 6. Show suspicious donations

* **Route:** anomaly  |  **Planned by:** rules
* **Tools:** `detect_anomalies` (analyst, ok, 387 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok

> Isolation Forest flags donation 121 (amount 980000, anomaly score 1.0).
> Isolation Forest flags donation 98 (amount 264, anomaly score 0.6423).
> Isolation Forest flags donation 117 (amount 3857, anomaly score 0.6092).

## 7. What is the average donation?

* **Route:** calculation  |  **Planned by:** rules
* **Tools:** `calculate` (analyst, ok, 2 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok

> Average donation: 9188.35 currency (over 126 monetary donation(s)).

## 8. How do I reset my password and what are recovery codes?

* **Route:** knowledge  |  **Planned by:** rules
* **Tools:** `retrieve_knowledge` (retriever, ok, 69 ms)
* **Checks:** schema ok, RAG ok, constraints ok, numbers grounded ok

> 1) Choose Forgot password and enter your email [1]. After resetting, sign in with the new password [1].
> 2) When two-step verification is turned on you receive 8 one-time recovery codes, shown only once [3]. If you lose your phone, enter a recovery code instead of the 6-digit code; each recovery code works one time [3].
