"""Bayesian optimisation: a Gaussian-process surrogate (Matern kernel) with the Expected Improvement acquisition function.

Used to tune model hyper-parameters with few evaluations. Written from scratch on scikit-learn so it needs no extra package.
Integer dimensions are rounded before evaluation; the search is deterministic for a given seed."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import norm
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern


@dataclass
class Result:
    best_x: dict
    best_value: float
    history: list = field(default_factory=list)   # [(params, value)] in evaluation order


def _decode(u: np.ndarray, space: dict) -> dict:
    out = {}
    for ui, (name, spec) in zip(u, space.items()):
        lo, hi, kind = spec[0], spec[1], (spec[2] if len(spec) > 2 else "float")
        if kind == "log":
            v = math.exp(math.log(lo) + ui * (math.log(hi) - math.log(lo)))
        else:
            v = lo + ui * (hi - lo)
        out[name] = int(round(v)) if kind == "int" else float(v)
    return out


def minimize(fn, space: dict, n_init: int = 5, n_iter: int = 12, seed: int = 7, n_candidates: int = 2000) -> Result:
    """Minimise fn(**params). space = {"name": (low, high, "float"|"int"|"log")}."""
    rng = np.random.default_rng(seed)
    d = len(space)
    X = rng.random((n_init, d))
    y = np.array([fn(**_decode(x, space)) for x in X], dtype=float)
    hist = [(_decode(x, space), float(v)) for x, v in zip(X, y)]
    for _ in range(n_iter):
        gp = GaussianProcessRegressor(kernel=ConstantKernel(1.0) * Matern(length_scale=np.ones(d), nu=2.5), alpha=1e-6, normalize_y=True,
                                      n_restarts_optimizer=2, random_state=int(rng.integers(1 << 30)))
        gp.fit(X, y)
        cand = rng.random((n_candidates, d))
        mu, sd = gp.predict(cand, return_std=True)
        best = y.min()
        imp = best - mu - 0.01
        z = np.where(sd > 0, imp / np.maximum(sd, 1e-12), 0.0)
        ei = np.where(sd > 0, imp * norm.cdf(z) + sd * norm.pdf(z), 0.0)
        x_new = cand[int(np.argmax(ei))]
        v_new = float(fn(**_decode(x_new, space)))
        X, y = np.vstack([X, x_new]), np.append(y, v_new)
        hist.append((_decode(x_new, space), v_new))
    i = int(np.argmin(y))
    return Result(_decode(X[i], space), float(y[i]), hist)
