"""Multi-agent orchestration (Agentic RAG).

    Router      classifies the question (Adaptive RAG) and splits multi-part questions (query decomposition)
    Planner     chooses tools                                  (rules, or an LLM whose plan is validated)
    Retriever   runs the knowledge tools                       (hybrid RAG, GraphRAG, CRAG, citations)
    Analyst     runs ML and Python tools                       (forecast, predict, anomalies, exact calculations)
    Optimizer   runs the constraint solvers                    (allocation, matching, routing) - proposals only
    Verifier    checks structure, citations, constraints, numbers and the approval policy (Self-RAG style)
    Explainer   writes the answer: a template over the tool results, or an LLM that may use ONLY numbers from those results

Consequential decisions are never executed. Optimizer tools create proposals in the review queue; `requires_approval` is set on the
result so the interface can say so, and a person approves each one. Every run is written to the audit trail."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...services import audit, live_assistant, live_retrieval
from ..rag import adaptive, answer as ans, decompose
from . import planner
from .tools import REGISTRY

AGENT_OF = {"knowledge": "retriever", "ml": "analyst", "python": "analyst", "optimization": "optimizer"}
EXTRA_NUMBERS = [14.0, 30.0, 100.0, 1.0, 2.0, 3.0]


def _numbers(obj: Any, out: list[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)
    elif isinstance(obj, str):
        out.extend(float(x.replace(",", "")) for x in re.findall(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?", obj))


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def explain_template(steps: list[dict]) -> str:
    """The default explainer: plain sentences built directly from the tool outputs, so every number is a tool result."""
    lines: list[str] = []
    for s in steps:
        if s["status"] != "ok":
            lines.append(f"{s['tool']} could not run: {s['error']}")
            continue
        o, t = s["output"], s["tool"]
        if t == "retrieve_knowledge":
            lines.append(o["answer"] if o["answerable"] else "The knowledge base does not contain a reliable answer to that.")
        elif t == "query_live_data":
            lines.extend(" ".join(ans.cite_sentence(x, 0)[:0] + x for x in ans.split_sentences(e["text"])[:3]) for e in o["evidence"][:2])
        elif t == "forecast_demand":
            for it in o["items"][:3]:
                bt = f", backtest error {it['backtest'][it['method']]['mae']} versus {it['backtest']['naive']['mae']} for the naive forecast" if it["method"] in it["backtest"] and "naive" in it["backtest"] else ""
                lines.append(f"Next month for {it['category']}: about {it['forecast']} request(s), using {it['method']}{bt}." + ("" if it["confident"] else " The history is short, so treat this as a rough estimate."))
            if not o["items"]:
                lines.append("There is not enough need history to forecast.")
        elif t == "predict_fulfilment":
            f = ", ".join(f"{x['feature'].replace('_', ' ')} ({'+' if x['effect'] >= 0 else ''}{round(100 * x['effect'])} points)" for x in o["factors"]) or "no model factors yet"
            lines.append(f"Need {o['need_id']} has a {_pct(o['probability'])} chance of being fulfilled within 14 days ({o['risk']} risk). Model: {o['model']}; main factors: {f}.")
        elif t == "simulate_shortfall":
            b = o["baseline"]
            lines.append(f"For {o['category']}, about {o['demand_forecast_units']} units are expected against {o['stock_units']} in stock: the chance of a shortfall is {_pct(b['p_shortfall'])}, with {b['expected_unmet']} units unmet on average.")
            for sc in o["scenarios"][:3]:
                lines.append(f"Adding {sc['extra']:g} units lowers the shortfall chance to {_pct(sc['p_shortfall'])}.")
        elif t == "detect_anomalies":
            if not o["items"]:
                lines.append(f"{o['method']} found nothing unusual.")
            for it in o["items"][:3]:
                lines.append(f"{o['method']} flags " + (f"donation {it['donation_id']} (amount {it['amount']:g}, anomaly score {it['anomaly_score']})" if "donation_id" in it else f"need {it['need_id']} ({it['category']}, quantity {it['quantity']})") + ".")
        elif t == "similar_needs":
            lines.append(f"Need {o['need_id']} resembles " + ", ".join(f"need {n['need_id']} ({n['category']})" for n in o["neighbours"][:3]) + "." if o["neighbours"] else "No similar past needs were found.")
        elif t == "calculate":
            lines.append(f"{o['metric'].replace('_', ' ').capitalize()}: {o['value']:g}{(' ' + o['unit']) if o['unit'] else ''}" + (f" ({o['detail']})." if o["detail"] else "."))
        elif t == "check_data_quality":
            lines.append(f"Data check: {o['errors']} error(s) and {o['warnings']} warning(s)." + ("" if o["ok"] else " Top issue: " + o["issues"][0]["title"] + "."))
        elif t == "optimize_allocation":
            mt, b = o["metrics"], o["baseline"]
            lines.append(f"The allocation plan gives out {mt['units_allocated']:g} units and leaves {mt['unmet_units']:g} unmet. Worst-served need reaches {_pct(mt['min_coverage'])} coverage (a greedy plan reaches {_pct(b['min_coverage'])}); fairness index {mt['jain']}.")
            if o["notes"]:
                lines.append("Note: " + "; ".join(o["notes"][:2]) + ".")
            lines.append(("It was checked against every inventory and demand limit: no violations." if not o["violations"] else "Constraint violations were found: " + "; ".join(o["violations"])) + " This is a proposal that needs human approval.")
            if o["proposals_created"]:
                lines.append(f"{len(o['proposals_created'])} proposal(s) were added to the review queue.")
        elif t == "optimize_matching":
            mt, b = o["metrics"], o["baseline"]
            lines.append(f"The matching covers {mt['needs_covered']} of {mt['needs_total']} needs (greedy covers {b['needs_covered']}) and {mt['orgs_covered']} organization(s). It respects every donor's capacity. This is a proposal that needs human approval.")
            if o["proposals_created"]:
                lines.append(f"{len(o['proposals_created'])} suggestion(s) were added to the review queue.")
        elif t == "plan_route":
            lines.append(f"{o['vehicles_needed']} route(s), {o['total_km']} km in total." + ("" if o["feasible"] else " " + " ".join(o["notes"])))
    return "\n".join(l for l in lines if l)


def run_agent(db: Session, question: str, user: dict, *, llm=None, llm_planner=None, create_proposals: bool = False, decompose_llm=None) -> dict:
    t0 = time.time()
    question = (question or "").strip()
    is_admin = user.get("role") == "admin"
    trace: list[dict] = []

    # ---- Router agent
    live_intents = live_assistant.classify(question) if user.get("role") != "volunteer" else []
    has_entities = live_retrieval.has_entities(live_retrieval.detect_entities(db, user, question)) if question else False
    route = adaptive.classify(question, live_intents, has_entities)
    subs = decompose.decompose(question, decompose_llm)
    trace.append({"agent": "router", "result": {"route": route["route"], "routes": route["routes"], "complexity": route["complexity"], "subquestions": [s["text"] for s in subs]}})

    if route["route"] == "chitchat":
        return {"question": question, "route": route, "plan": [], "steps": [], "answer": "Hello! Ask me about how CareBridge AI works, current needs, forecasts, risks or allocation plans.", "citations": [], "proposals": [],
                "requires_approval": False, "validation": {"schema_ok": True, "rag_ok": True, "constraints_ok": True, "numbers_ok": True, "ungrounded": [], "warnings": []}, "mode": "no_tools", "trace": trace,
                "duration_ms": int((time.time() - t0) * 1000)}

    # ---- Planner agent
    plan, planned_by = planner.make_plan(db, user, question, route, llm_planner)
    trace.append({"agent": "planner", "result": {"planned_by": planned_by, "steps": [{"tool": p["tool"], "why": p["why"]} for p in plan]}})

    # ---- Retriever / Analyst / Optimizer agents
    steps: list[dict] = []
    warnings: list[str] = []
    for p in plan:
        tool = REGISTRY[p["tool"]]
        step = {"tool": tool.name, "kind": tool.kind, "agent": AGENT_OF[tool.kind], "args": p["args"], "why": p["why"], "requires_approval": tool.requires_approval}
        s0 = time.time()
        if tool.admin_only and not is_admin:
            step.update(status="denied", error="This tool is available to administrators only.", output=None)
        else:
            try:
                args = dict(p["args"])
                if tool.requires_approval:
                    args["create_proposals"] = bool(create_proposals and is_admin)
                parsed = tool.input.model_validate(args)
                out = tool.run(db, user, parsed)
                step["output"] = tool.output.model_validate(out).model_dump()        # structured output must validate
                step["status"] = "ok"
            except ValidationError as exc:
                step.update(status="error", error=f"output or input failed validation: {exc.errors()[0]['msg']}", output=None)
            except Exception as exc:  # a failing tool must not stop the others
                db.rollback()
                step.update(status="error", error=str(exc)[:200], output=None)
        step["ms"] = int((time.time() - s0) * 1000)
        steps.append(step)
    trace.append({"agent": "tools", "result": [{"tool": s["tool"], "agent": s["agent"], "status": s["status"], "ms": s["ms"]} for s in steps]})

    # ---- Explainer agent (template, or an LLM restricted to the tool results)
    allowed: list[float] = []
    for s in steps:
        if s["status"] == "ok":
            _numbers(s["output"], allowed)
        _numbers(s["args"], allowed)
    allowed += EXTRA_NUMBERS
    answer_text, mode = explain_template(steps), "template"
    if llm is not None and any(s["status"] == "ok" for s in steps):
        facts = json.dumps([{"tool": s["tool"], "output": s["output"]} for s in steps if s["status"] == "ok"], default=str)[:12000]
        prompt = ("Explain these tool results to a non-technical administrator in at most 8 sentences. Use ONLY numbers that appear in the results. "
                  "Do not add facts. If a result is a proposal, say that it needs human approval.\n\nResults:\n" + facts)
        try:
            cand = (llm(prompt) or "").strip()
            chk = ans.numbers_grounded(cand, [], allowed)
            if cand and chk["ok"]:
                answer_text, mode = cand, "llm_verified"
            else:
                warnings.append("The language model's explanation used numbers that are not in the tool results, so the template explanation was used instead.")
        except Exception:
            warnings.append("The language model was unavailable; the template explanation was used.")

    # ---- Verifier agent
    ok_steps = [s for s in steps if s["status"] == "ok"]
    rag = [s for s in ok_steps if s["tool"] == "retrieve_knowledge"]
    rag_ok = all(s["output"]["validation"].get("ok", True) and s["output"]["validation"]["numbers"]["ok"] for s in rag) if rag else True
    violations = [v for s in ok_steps if s["tool"].startswith("optimize_") for v in s["output"]["violations"]]
    numbers = ans.numbers_grounded(answer_text, [e["text"] for s in rag for e in s["output"]["evidence"]] + [e["text"] for s in ok_steps if s["tool"] == "query_live_data" for e in s["output"]["evidence"]], allowed)
    schema_ok = all(s["status"] != "error" or "validation" not in (s.get("error") or "") for s in steps)
    proposals = [p for s in ok_steps if s["tool"].startswith("optimize_") for p in s["output"]["proposals_created"]]
    requires_approval = any(s["requires_approval"] and s["status"] == "ok" for s in steps)
    if create_proposals and not is_admin:
        warnings.append("Only administrators can create proposals; none were created.")
    if any(s["status"] == "denied" for s in steps):
        warnings.append("Some tools were skipped because they are available to administrators only.")
    trace.append({"agent": "verifier", "result": {"schema_ok": schema_ok, "rag_ok": rag_ok, "constraints_ok": not violations, "numbers_ok": numbers["ok"], "requires_approval": requires_approval}})
    citations = [c for s in rag for c in s["output"]["citations"]]
    if proposals:
        audit.record(db, user, "agent.proposals_created", "agent_run", None, {"count": len(proposals), "types": sorted({p["type"] for p in proposals})})
    audit.record(db, user, "agent.run", "agent_run", None, {"question": question[:200], "tools": [s["tool"] for s in steps], "planned_by": planned_by, "mode": mode, "proposals": len(proposals)})
    db.commit()
    return {"question": question, "route": route, "plan": plan, "planned_by": planned_by, "steps": steps, "answer": answer_text, "citations": citations, "proposals": proposals,
            "requires_approval": requires_approval, "mode": mode,
            "validation": {"schema_ok": schema_ok, "rag_ok": rag_ok, "constraints_ok": not violations, "numbers_ok": numbers["ok"], "ungrounded": numbers["ungrounded"], "warnings": warnings},
            "trace": trace, "duration_ms": int((time.time() - t0) * 1000)}
