"""A small discrete Bayesian network for need fulfilment, with exact inference by enumeration.

    Urgency (0..3)   DonorCover (0/1)   StockCover (0/1)   ->   Fulfilled (0/1)

CPTs are learned from counts with Dirichlet (+1) smoothing. Because the structure is explicit, administrators can ask causal-style
questions such as "how much would adding stock raise the chance of fulfilment for this need?" using do(StockCover=1) vs do(StockCover=0).
It is intentionally tiny: the structure is expert-chosen, not learned."""
from __future__ import annotations

import itertools

import pandas as pd

ROOTS = {"urgency": 4, "donor_cover": 2, "stock_cover": 2}


def discretise(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"urgency": df["urgency"].astype(int).clip(0, 3), "donor_cover": (df["donor_coverage"] >= 2).astype(int),
                         "stock_cover": (df["resource_coverage"] >= 0.5).astype(int), "fulfilled": df["label"].astype(int)})


class NeedBayesNet:
    def fit(self, df: pd.DataFrame):
        d = discretise(df)
        self.prior = {n: ((d[n].value_counts().reindex(range(k), fill_value=0) + 1) / (len(d) + k)).to_dict() for n, k in ROOTS.items()}
        self.cpt = {}
        for u, dc, sc in itertools.product(range(4), range(2), range(2)):
            sub = d[(d["urgency"] == u) & (d["donor_cover"] == dc) & (d["stock_cover"] == sc)]
            self.cpt[(u, dc, sc)] = (sub["fulfilled"].sum() + 1) / (len(sub) + 2)
        self.rows = len(d)
        return self

    def p_fulfilled(self, **evidence) -> float:
        """P(Fulfilled=1 | evidence). Unspecified roots are marginalised with their learned priors."""
        total = 0.0
        for u, dc, sc in itertools.product(range(4), range(2), range(2)):
            vals = {"urgency": u, "donor_cover": dc, "stock_cover": sc}
            if any(vals[k] != v for k, v in evidence.items()):
                continue
            w = 1.0
            for n in ROOTS:
                if n not in evidence:
                    w *= self.prior[n][vals[n]]
            total += w * self.cpt[(u, dc, sc)]
        norm = 0.0
        for u, dc, sc in itertools.product(range(4), range(2), range(2)):
            vals = {"urgency": u, "donor_cover": dc, "stock_cover": sc}
            if any(vals[k] != v for k, v in evidence.items()):
                continue
            w = 1.0
            for n in ROOTS:
                if n not in evidence:
                    w *= self.prior[n][vals[n]]
            norm += w
        return float(total / norm) if norm else 0.0

    def do_effect(self, node: str, **given) -> dict:
        """Intervention: P(F | evidence, do(node=1)) minus P(F | evidence, do(node=0)). Roots have no parents, so do() equals fixing the value."""
        hi, lo = self.p_fulfilled(**{**given, node: 1}), self.p_fulfilled(**{**given, node: 0})
        return {"with": round(hi, 4), "without": round(lo, 4), "effect": round(hi - lo, 4)}
