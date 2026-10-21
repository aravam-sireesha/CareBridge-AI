"""Planner agent: turn a question into an ordered list of tool calls.

Rule-based by default (transparent, tested). If a language model is supplied it may propose the plan as JSON, but every step is
validated against the tool registry and its input model; anything invalid is dropped and, if nothing valid remains, the rules decide."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from ...services import live_retrieval
from ..rag import adaptive
from .tools import REGISTRY

MAX_STEPS = 6
CATEGORY_WORDS = ["books", "food", "meals", "clothes", "clothing", "medicine", "medical", "education", "tutoring", "school supplies", "blankets", "toys", "shoes", "uniforms", "health"]
METRIC_WORDS = [(r"average (donation|gift)|mean (donation|gift)", "average_donation"), (r"total (donat\w+|given|raised)|how much .*(donated|raised|given)", "total_donated"),
                (r"(number|count) of donations|how many donations", "donation_count"), (r"open needs|how many (open )?needs", "open_needs"),
                (r"fulfil\w* rate|percent\w* (of needs )?fulfil\w*", "fulfilment_rate"), (r"in stock|stock units|inventory", "units_in_stock"),
                (r"allocated", "units_allocated"), (r"beneficiar\w+|children (affected|helped)", "beneficiaries_open")]


def extract_need_id(q: str) -> int | None:
    m = re.search(r"\bneed\s*(?:#|number|no\.?|id)?\s*(\d+)\b", q, re.I)
    return int(m.group(1)) if m else None


def extract_category(db, viewer: dict, q: str) -> str | None:
    cats = live_retrieval.detect_entities(db, viewer, q)["categories"]
    if cats:
        return cats[0]
    low = q.lower()
    return next((w for w in CATEGORY_WORDS if re.search(rf"\b{re.escape(w)}\b", low)), None)


def extract_expression(q: str) -> str | None:
    m = re.search(r"(?<![\w.])(\(?\s*\d[\d.,]*\s*(?:[-+*/%]|\*\*)\s*[\d(][\d\s.,+\-*/%()]*)", q)
    return re.sub(r"[,\s]+(?=\d)", "", m.group(1)).strip() if m else None


def rule_plan(db, viewer: dict, question: str, route: dict) -> list[dict]:
    q = question.lower()
    steps: list[dict] = []

    def add(tool, args, why):
        if tool in REGISTRY and not any(s["tool"] == tool and s["args"] == args for s in steps):
            steps.append({"tool": tool, "args": args, "why": why})

    need_id = extract_need_id(question)
    cat = extract_category(db, viewer, question)
    for r in route["routes"]:
        if r == "knowledge":
            add("retrieve_knowledge", {"question": question}, "The question asks how something works: retrieve it from the knowledge base with citations.")
        elif r == "live_data":
            add("query_live_data", {"question": question}, "The question is about the current state of the platform: read it from the live database.")
        elif r == "prediction":
            if need_id:
                add("predict_fulfilment", {"need_id": need_id}, "Predict whether this need will be fulfilled in time.")
                add("similar_needs", {"need_id": need_id}, "Look at similar past needs for context.")
            elif cat:
                add("forecast_demand", {"category": cat}, "Forecast demand for the category with a backtested model.")
                add("simulate_shortfall", {"category": cat}, "Simulate supply against the forecast to estimate the risk of a shortfall.")
            else:
                add("forecast_demand", {}, "Forecast demand for the categories with enough history.")
        elif r == "optimization":
            if re.search(r"\b(route|routing|vehicle|truck|deliver\w*)\b", q):
                add("plan_route", {}, "Plan delivery routes under vehicle capacity.")
            elif re.search(r"\b(donor|donors|sponsor\w*|match\w*)\b", q):
                add("optimize_matching", {}, "Match donors to needs under capacity and coverage constraints.")
            else:
                add("optimize_allocation", {"fairness": "maxmin" if re.search(r"fair|equal|share", q) or True else "none", "urgent_first": True}, "Allocate scarce stock with inventory, urgency and fairness constraints.")
        elif r == "calculation":
            expr = extract_expression(question)
            if expr:
                add("calculate", {"expression": expr}, "Compute the arithmetic exactly in Python.")
            else:
                metric = next((mt for pat, mt in METRIC_WORDS if re.search(pat, q)), None)
                if metric:
                    add("calculate", {"metric": metric, **({"category": cat} if cat else {})}, "Compute the figure exactly in Python from the database.")
                else:
                    add("query_live_data", {"question": question}, "No exact metric recognised: read the live data instead.")
        elif r == "anomaly":
            add("detect_anomalies", {"scope": "needs" if re.search(r"\bneeds?\b", q) and "donation" not in q else "donations"}, "Look for unusual records with an unsupervised model.")
    if re.search(r"data quality|data integrity|consistent|inconsisten|orphan|validate the data", q):
        add("check_data_quality", {}, "Verify that the underlying records are consistent.")
    if not steps:
        add("retrieve_knowledge", {"question": question}, "Default: search the knowledge base.")
    return steps[:MAX_STEPS]


def llm_plan(llm, question: str) -> list[dict] | None:
    """`llm(prompt) -> str` should return JSON: [{"tool": ..., "args": {...}, "why": ...}]. Invalid steps are discarded."""
    specs = [{"name": t.name, "description": t.description, "input": t.input.model_json_schema().get("properties", {})} for t in REGISTRY.values()]
    prompt = ("Choose the tools needed to answer the question. Reply with JSON only: a list of {\"tool\", \"args\", \"why\"}. "
              f"At most {MAX_STEPS} steps. Tools: {json.dumps(specs)}\nQuestion: {question}")
    try:
        raw = llm(prompt)
        data = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
    except Exception:
        return None
    out = []
    for step in data if isinstance(data, list) else []:
        try:
            tool = REGISTRY[step["tool"]]
            args = tool.input.model_validate(step.get("args") or {}).model_dump()
        except (KeyError, TypeError, ValidationError):
            continue
        out.append({"tool": tool.name, "args": args, "why": str(step.get("why", ""))[:200]})
    return out[:MAX_STEPS] or None


def make_plan(db, viewer, question, route=None, llm=None) -> tuple[list[dict], str]:
    route = route or adaptive.classify(question)
    if llm is not None:
        steps = llm_plan(llm, question)
        if steps:
            return steps, "llm"
    return rule_plan(db, viewer, question, route), "rules"
