"""The agent's tools. Division of labour (the architecture this module enforces):

    RAG                    retrieves KNOWLEDGE                (retrieve_knowledge, query_live_data)
    Machine learning       PREDICTS outcomes                  (forecast_demand, predict_fulfilment, detect_anomalies, similar_needs, simulate_shortfall)
    Python                 CALCULATES values exactly          (calculate, check_data_quality)
    Optimisation           makes CONSTRAINED decisions        (optimize_allocation, optimize_matching, plan_route)
    The language model     only EXPLAINS the results          (see orchestrator)

Every tool has a typed input model and a typed output model; output that does not validate is rejected. Tools that could change real
records are marked `requires_approval`: they only ever create PROPOSALS (status 'proposed' / 'suggested') that a person approves in the
review queue. Nothing here approves, verifies, delivers or spends anything."""
from __future__ import annotations

import ast
import operator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import models as m
from ...services import donor_ml, resource_allocation
from ...services.matching_rules import _normalize, _tag_match_score
from ..data_quality import check as dq_check
from ..ml import anomaly_ml, dataset, forecast_models, need_model, simulate
from ..optim import allocation as al
from ..optim import routing
from ..rag import pipeline


# ----------------------------------------------------------------------------- input / output models
class QuestionIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class ForecastIn(BaseModel):
    category: Optional[str] = Field(default=None, max_length=100)


class NeedIn(BaseModel):
    need_id: int = Field(gt=0)


class SimIn(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    extra_units: list[float] = Field(default_factory=lambda: [10.0, 25.0, 50.0], max_length=6)


class AnomalyIn(BaseModel):
    scope: Literal["donations", "needs"] = "donations"
    top_n: int = Field(default=5, ge=1, le=20)


class CalcIn(BaseModel):
    metric: Optional[Literal["total_donated", "average_donation", "donation_count", "open_needs", "fulfilment_rate", "units_in_stock", "units_allocated", "beneficiaries_open"]] = None
    expression: Optional[str] = Field(default=None, max_length=200)
    organization_id: Optional[int] = None
    category: Optional[str] = Field(default=None, max_length=100)


class AllocIn(BaseModel):
    fairness: Literal["none", "floor", "maxmin"] = "maxmin"
    urgent_first: bool = True
    org_cap: Optional[float] = Field(default=None, gt=0, le=1)
    create_proposals: bool = False


class MatchIn(BaseModel):
    donor_capacity: int = Field(default=2, ge=1, le=10)
    max_donors_per_need: int = Field(default=2, ge=1, le=5)
    create_proposals: bool = False


class StopIn(BaseModel):
    id: int
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    demand: float = Field(gt=0)


class RouteIn(BaseModel):
    depot_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    depot_lon: Optional[float] = Field(default=None, ge=-180, le=180)
    stops: list[StopIn] = Field(default_factory=list, max_length=60)
    vehicles: int = Field(default=2, ge=1, le=20)
    capacity: float = Field(default=100, gt=0)


class Empty(BaseModel):
    pass


class KnowledgeOut(BaseModel):
    answer: str
    answerable: bool
    confidence: float = Field(ge=0, le=1)
    evidence: list[dict]
    citations: list[dict]
    validation: dict


class LiveOut(BaseModel):
    evidence: list[dict]


class ForecastItem(BaseModel):
    category: str
    method: str
    forecast: float = Field(ge=0)
    history: list[float]
    confident: bool
    backtest: dict = {}
    skill_vs_naive: Optional[float] = None


class ForecastOut(BaseModel):
    items: list[ForecastItem]


class PredictOut(BaseModel):
    need_id: int
    probability: float = Field(ge=0, le=1)
    risk: Literal["low", "medium", "high"]
    model: str
    trained_on: str
    factors: list[dict]
    note: str


class SimOut(BaseModel):
    category: str
    demand_forecast_units: float = Field(ge=0)
    stock_units: float = Field(ge=0)
    pledged_units: float = Field(ge=0)
    baseline: dict
    scenarios: list[dict]


class AnomalyOut(BaseModel):
    scope: str
    items: list[dict]
    method: str


class CalcOut(BaseModel):
    metric: str
    value: float
    unit: str = ""
    detail: str = ""


class OptOut(BaseModel):
    kind: Literal["allocation", "matching"]
    metrics: dict
    allocations: list[dict] = []
    assignments: list[dict] = []
    baseline: dict
    notes: list[str]
    violations: list[str]
    proposals_created: list[dict] = []
    requires_approval: bool = True


class RouteOut(BaseModel):
    routes: list[dict]
    total_km: float = Field(ge=0)
    vehicles_needed: int
    feasible: bool
    notes: list[str]


class QualityOut(BaseModel):
    ok: bool
    errors: int
    warnings: int
    issues: list[dict]


class SimilarOut(BaseModel):
    need_id: int
    neighbours: list[dict]


# ----------------------------------------------------------------------------- the registry
@dataclass
class Tool:
    name: str
    description: str
    input: type[BaseModel]
    output: type[BaseModel]
    run: Callable[[Session, dict, BaseModel], dict]
    kind: str                       # knowledge | ml | python | optimization
    admin_only: bool = True
    requires_approval: bool = False

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "kind": self.kind, "admin_only": self.admin_only, "requires_approval": self.requires_approval,
                "input_schema": self.input.model_json_schema()}


def _open_needs(db):
    return [n for n in db.query(m.Need).all() if (n.status or "").lower() in donor_ml.OPEN_STATUSES]


# ----- knowledge
def t_retrieve(db, user, a: QuestionIn):
    out = pipeline.answer_question(db, a.question, user, cross_encoder="auto", with_live=False)
    return {"answer": out["answer"], "answerable": out["answerable"], "confidence": out["confidence"], "evidence": out["evidence"], "citations": out["citations"], "validation": out["validation"]}


def t_live(db, user, a: QuestionIn):
    return {"evidence": pipeline.live_evidence(db, user, a.question)}


# ----- ML
def t_forecast(db, user, a: ForecastIn):
    series = forecast_models.category_series(db)
    wanted = {_normalize(a.category)} if a.category else set(series)
    items = []
    for cat, s in series.items():
        if _normalize(cat) in wanted or any(_tag_match_score(a.category or "", cat) > 0 for _ in [0] if a.category):
            f = forecast_models.forecast_series(s)
            items.append({"category": cat, "method": f["method"], "forecast": f["forecast"], "history": s, "confident": f["confident"], "backtest": f.get("backtest", {}), "skill_vs_naive": f.get("skill_vs_naive")})
    items.sort(key=lambda i: -i["forecast"])
    return {"items": items[:10]}


def t_predict(db, user, a: NeedIn):
    need = db.get(m.Need, a.need_id)
    if need is None:
        raise LookupError("Need not found")
    return need_model.predict(db, need)


def t_simulate(db, user, a: SimIn):
    series = forecast_models.category_series(db)
    key = next((c for c in series if _tag_match_score(a.category, c) > 0 or _normalize(c) == _normalize(a.category)), None)
    f = forecast_models.forecast_series(series[key]) if key else {"forecast": 0.0}
    qty_per_need = [n.quantity or 0 for n in _open_needs(db) if _tag_match_score(a.category, n.category or "") > 0 or _normalize(n.category) == _normalize(a.category)]
    mean_units = float(f["forecast"]) * (sum(qty_per_need) / len(qty_per_need) if qty_per_need else 1.0)
    stock = float(sum(r.quantity_available for r in db.query(m.Resource).filter_by(status="available").all()
                      if max(_tag_match_score(a.category, r.category or ""), _tag_match_score(a.category, r.name or "")) > 0))
    pledged = float(sum(d.amount or 0 for d in db.query(m.Donation).filter(m.Donation.status.in_(("pledged", "in_transit"))).all()) if hasattr(m.Donation, "status") else 0.0)
    delivered = db.query(m.Donation).filter(m.Donation.status.in_(("delivered", "confirmed"))).count() if hasattr(m.Donation, "status") else 0
    total_pledges = db.query(m.Donation).count()
    pa, pb = simulate.beta_from_rate(delivered, max(total_pledges, 1))
    sd = max(0.25 * mean_units, 1.0)
    table = simulate.compare_allocation(mean_units, sd, stock, a.extra_units, pledged_units=0.0, pledge_a=pa, pledge_b=pb)
    return {"category": a.category, "demand_forecast_units": round(mean_units, 2), "stock_units": stock, "pledged_units": 0.0, "baseline": table[0], "scenarios": table[1:]}


def t_anomalies(db, user, a: AnomalyIn):
    if a.scope == "needs":
        out = anomaly_ml.cluster_needs(db)
        return {"scope": "needs", "method": "DBSCAN (density clustering)", "items": out["outliers"][: a.top_n]}
    frame = anomaly_ml.donation_frame(db)
    scored = anomaly_ml.isolation_scores(frame)
    top = scored.sort_values("anomaly_score", ascending=False).head(a.top_n)
    return {"scope": "donations", "method": "Isolation Forest", "items": [{"donation_id": int(r.donation_id), "donor_id": int(r.donor_id), "amount": float(r.amount), "anomaly_score": float(r.anomaly_score), "reasons": r.reasons}
                                                                          for r in top.itertuples() if r.anomaly_score > 0]}


def t_similar(db, user, a: NeedIn):
    need = db.get(m.Need, a.need_id)
    if need is None:
        raise LookupError("Need not found")
    return {"need_id": need.id, "neighbours": anomaly_ml.similar_needs(db, need, k=5)}


# ----- Python calculation
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Mod: operator.mod}


def safe_eval(expr: str) -> float:
    """Arithmetic only: numbers, + - * / ** % and parentheses. No names, calls or attributes."""
    def ev(node, depth=0):
        if depth > 20:
            raise ValueError("expression too deep")
        if isinstance(node, ast.Expression):
            return ev(node.body, depth + 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            l, r = ev(node.left, depth + 1), ev(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(r) > 12:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](l, r)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand, depth + 1))
        raise ValueError("only arithmetic is allowed")
    return float(ev(ast.parse(expr.strip(), mode="eval")))


def t_calculate(db, user, a: CalcIn):
    if a.expression:
        return {"metric": "expression", "value": safe_eval(a.expression), "detail": a.expression}
    if not a.metric:
        raise ValueError("give a metric or an expression")
    needs = db.query(m.Need)
    if a.organization_id:
        needs = needs.filter(m.Need.org_id == a.organization_id)
    needs = [n for n in needs.all() if not a.category or _normalize(n.category) == _normalize(a.category) or _tag_match_score(a.category, n.category or "") > 0]
    ids = {n.id for n in needs}
    gifts = [d for d in db.query(m.Donation).all() if d.need_id in ids]
    if a.metric == "total_donated":
        return {"metric": a.metric, "value": float(sum(d.amount or 0 for d in gifts)), "unit": "currency", "detail": f"{len(gifts)} donation(s)"}
    if a.metric == "average_donation":
        paid = [d.amount for d in gifts if d.amount]
        return {"metric": a.metric, "value": float(sum(paid) / len(paid)) if paid else 0.0, "unit": "currency", "detail": f"over {len(paid)} monetary donation(s)"}
    if a.metric == "donation_count":
        return {"metric": a.metric, "value": float(len(gifts))}
    if a.metric == "open_needs":
        return {"metric": a.metric, "value": float(sum(1 for n in needs if (n.status or "").lower() in donor_ml.OPEN_STATUSES))}
    if a.metric == "fulfilment_rate":
        done = sum(1 for n in needs if (n.status or "").lower() == "fulfilled")
        return {"metric": a.metric, "value": round(100.0 * done / len(needs), 2) if needs else 0.0, "unit": "%", "detail": f"{done} of {len(needs)} needs"}
    if a.metric == "units_in_stock":
        return {"metric": a.metric, "value": float(db.query(func.coalesce(func.sum(m.Resource.quantity_available), 0)).scalar() or 0), "unit": "units"}
    if a.metric == "units_allocated":
        return {"metric": a.metric, "value": float(db.query(func.coalesce(func.sum(m.ResourceAllocation.quantity), 0)).filter(m.ResourceAllocation.status.in_(("approved", "delivered"))).scalar() or 0), "unit": "units"}
    return {"metric": a.metric, "value": float(sum(n.beneficiaries or 0 for n in needs if (n.status or "").lower() in donor_ml.OPEN_STATUSES)), "unit": "children"}


def t_quality(db, user, a: Empty):
    r = dq_check(db)
    return {"ok": r["ok"], "errors": r["errors"], "warnings": r["warnings"], "issues": [{k: i[k] for k in ("code", "severity", "title", "count", "hint")} for i in r["issues"]]}


# ----- optimisation
def _build_allocation(db):
    needs = _open_needs(db)
    S = [al.Supply(r.id, float(r.quantity_available), r.organization_id) for r in db.query(m.Resource).filter_by(status="available").all() if r.quantity_available > 0]
    D, compat = [], {}
    res = {s.id: db.get(m.Resource, s.id) for s in S}
    for n in needs:
        remaining = max(0, (n.quantity or 0) - resource_allocation.committed_quantity(db, n.id))
        if remaining <= 0:
            continue
        urg = (n.urgency or "medium").lower()
        D.append(al.Demand(n.id, float(remaining), al.URGENCY_WEIGHT.get(urg, 1.5), n.org_id, urg == "critical"))
        for s in S:
            r = res[s.id]
            rel = max(_tag_match_score(n.category, r.category or ""), _tag_match_score(n.category, r.name or ""))
            if rel > 0:
                compat[(s.id, n.id)] = rel
    return S, D, compat


def t_optimize_alloc(db, user, a: AllocIn):
    S, D, compat = _build_allocation(db)
    res = al.solve_allocation(S, D, compat, fairness=a.fairness, urgent_first=a.urgent_first, org_cap=a.org_cap)
    base = al.greedy_allocation(S, D, compat)
    violations = al.check_feasibility(S, D, res)
    created = []
    if a.create_proposals and not violations:
        for x in res["allocations"]:
            row = db.query(m.ResourceAllocation).filter_by(need_id=x["demand_id"], resource_id=x["supply_id"], status="proposed").first()
            reasons = [f"Optimizer ({res['method']}): relevance {round(x['relevance'], 2)}, fairness '{a.fairness}'" + (", urgent needs first" if a.urgent_first else "")]
            if row is None:
                row = m.ResourceAllocation(need_id=x["demand_id"], resource_id=x["supply_id"], quantity=int(x["units"]), score=x["relevance"], reasons=reasons, status="proposed", proposed_by=user.get("id"))
                db.add(row)
            else:
                row.quantity, row.score, row.reasons = int(x["units"]), x["relevance"], reasons
            db.flush()
            created.append({"type": "allocation", "id": row.id, "need_id": row.need_id, "resource_id": row.resource_id, "quantity": row.quantity, "status": row.status})
    return {"kind": "allocation", "metrics": res["metrics"], "allocations": res["allocations"], "baseline": base["metrics"], "notes": res["notes"], "violations": violations, "proposals_created": created}


def t_optimize_match(db, user, a: MatchIn):
    needs = _open_needs(db)
    donors = db.query(m.Donor).all()
    ctx = donor_ml.DonorContext(db)
    learned = donor_ml.train_learned_model(db)
    fit = {}
    for n in needs:
        for c in donor_ml.suggest_donors(db, n, top_n=len(donors) or 1, ctx=ctx, learned=learned):
            fit[(c["donor_id"], n.id)] = c["fit_score"]
    d_in = [{"id": d.id, "capacity": a.donor_capacity} for d in donors]
    n_in = [{"id": n.id, "weight": al.URGENCY_WEIGHT.get((n.urgency or "medium").lower(), 1.5), "org_id": n.org_id} for n in needs]
    res = al.solve_matching(d_in, n_in, fit, max_donors_per_need=a.max_donors_per_need)
    base = al.greedy_matching(d_in, n_in, fit, a.max_donors_per_need)
    violations = []
    load = {}
    for x in res["assignments"]:
        load[x["donor_id"]] = load.get(x["donor_id"], 0) + 1
    violations += [f"donor {d} assigned {c} needs (capacity {a.donor_capacity})" for d, c in load.items() if c > a.donor_capacity]
    created = []
    if a.create_proposals and not violations:
        urg = {n.id: donor_ml.score_need(n)["score"] for n in needs}
        for x in res["assignments"]:
            if db.query(m.DonorSuggestion).filter_by(need_id=x["need_id"], donor_id=x["donor_id"]).first():
                continue
            row = m.DonorSuggestion(need_id=x["need_id"], donor_id=x["donor_id"], fit_score=x["fit"], urgency_score=urg.get(x["need_id"], 0.5), priority_score=round(0.5 * urg.get(x["need_id"], 0.5) + 0.5 * x["fit"], 3),
                                    rank_in_need=1, reasons=["Chosen by the matching optimizer (capacity, coverage and fairness constraints)"], features=None, model_version="milp-matching-1.0", status="suggested", generated_by=user.get("id"))
            db.add(row)
            db.flush()
            created.append({"type": "donor_suggestion", "id": row.id, "need_id": row.need_id, "donor_id": row.donor_id, "status": row.status})
    return {"kind": "matching", "metrics": res["metrics"], "assignments": res["assignments"], "baseline": base["metrics"], "notes": res["notes"], "violations": violations, "proposals_created": created}


def t_route(db, user, a: RouteIn):
    stops = [s.model_dump() for s in a.stops]
    depot = (a.depot_lat, a.depot_lon) if a.depot_lat is not None and a.depot_lon is not None else None
    if not stops:
        for n in _open_needs(db):
            if n.latitude is not None and n.longitude is not None:
                stops.append({"id": n.id, "lat": n.latitude, "lon": n.longitude, "demand": float(n.quantity or 1)})
    if depot is None:
        org = next((o for o in db.query(m.Organization).all() if o.latitude is not None), None)
        depot = (org.latitude, org.longitude) if org else None
    if depot is None or not stops:
        raise ValueError("Routing needs a depot and stops with coordinates (latitude and longitude on organizations and needs).")
    return routing.solve_vrp(depot, stops, a.vehicles, a.capacity)


REGISTRY: dict[str, Tool] = {t.name: t for t in [
    Tool("retrieve_knowledge", "Answer from the approved knowledge base with citations (hybrid retrieval, reranking, GraphRAG, corrective RAG).", QuestionIn, KnowledgeOut, t_retrieve, "knowledge", admin_only=False),
    Tool("query_live_data", "Read live organizations, needs, donors and health scores from the database (scoped to the asker's role).", QuestionIn, LiveOut, t_live, "knowledge", admin_only=False),
    Tool("forecast_demand", "Forecast next month's number of needs per category with a backtested time-series model.", ForecastIn, ForecastOut, t_forecast, "ml"),
    Tool("predict_fulfilment", "Probability that a need is fulfilled within 14 days, with the main factors.", NeedIn, PredictOut, t_predict, "ml"),
    Tool("simulate_shortfall", "Monte Carlo simulation of supply against forecast demand for a category, with candidate extra allocations.", SimIn, SimOut, t_simulate, "ml"),
    Tool("detect_anomalies", "Find unusual donations (Isolation Forest) or unusual needs (DBSCAN).", AnomalyIn, AnomalyOut, t_anomalies, "ml"),
    Tool("similar_needs", "Find the most similar past needs (K-nearest neighbours) and how long they took.", NeedIn, SimilarOut, t_similar, "ml"),
    Tool("calculate", "Exact arithmetic and database aggregates computed in Python (never by the language model).", CalcIn, CalcOut, t_calculate, "python"),
    Tool("check_data_quality", "Verify relationships, inventory consistency and calculation rules.", Empty, QualityOut, t_quality, "python"),
    Tool("optimize_allocation", "Allocate scarce resources to needs with inventory, urgency and fairness constraints (LP/MILP). Creates PROPOSALS only.", AllocIn, OptOut, t_optimize_alloc, "optimization", requires_approval=True),
    Tool("optimize_matching", "Match donors to needs with capacity, coverage and fairness constraints (MILP). Creates PROPOSALS only.", MatchIn, OptOut, t_optimize_match, "optimization", requires_approval=True),
    Tool("plan_route", "Plan delivery routes (capacitated VRP) for stops with coordinates.", RouteIn, RouteOut, t_route, "optimization"),
]}
