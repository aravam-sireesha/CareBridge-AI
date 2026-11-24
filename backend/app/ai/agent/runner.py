"""Plan -> approve -> execute workflow around the existing planner, tools and verifier.

`propose` only PLANS: it classifies the goal, asks the planner for tool calls and describes each one. Nothing runs.
`execute` runs an APPROVED plan one step at a time and yields progress events, so the interface can show each tool as it
starts and finishes. Rules that never bend:
  * every step is re-validated against the tool registry and its typed input (the stored plan is not trusted);
  * administrator-only tools are refused for everyone else, whatever the plan says;
  * tools that could change records only ever create PROPOSALS for the review queue, and only when the person explicitly
    approved that and is an administrator;
  * a time budget and one retry for read-only tools bound the run;
  * a step is reported as done only if its output validated against the tool's output model.
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterator

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...services import live_assistant, live_retrieval
from ..rag import adaptive, answer as ans, decompose
from . import planner
from .orchestrator import AGENT_OF, EXTRA_NUMBERS, _numbers, explain_template
from .tools import REGISTRY

TIME_BUDGET_SECONDS = 90
GREETING = "Hello! Describe a goal, for example “analyse resource shortages and prioritise them”, and I will propose a plan for you to approve."
EXAMPLES = {
    "admin": ["Analyse food and medicine shortages and tell me which needs to fund first",
              "Find unusual donations and explain why they were flagged",
              "Allocate available stock fairly across all open needs",
              "Match donors to open needs under their capacity",
              "Check the data for inconsistencies, then forecast demand for next month"],
    "organization": ["Forecast demand for our top categories next month",
                     "What is the chance that need 1 is fulfilled in time, and which past needs are similar?",
                     "Summarise our current donation totals and open needs"],
    "donor": ["Which open needs would my donation help most?"],
    "volunteer": ["Explain how volunteer matching works"],
}


def _clean(obj: Any) -> Any:
    """JSON-safe copy (datetimes, numpy scalars ... become plain values) so results can be stored and streamed."""
    import json
    return json.loads(json.dumps(obj, default=str))


def describe_step(index: int, p: dict, user: dict) -> dict:
    tool = REGISTRY[p["tool"]]
    return {"index": index, "tool": tool.name, "kind": tool.kind, "agent": AGENT_OF[tool.kind], "description": tool.description, "why": p["why"],
            "args": _clean(p["args"]), "requires_approval": tool.requires_approval, "admin_only": tool.admin_only,
            "allowed": not (tool.admin_only and user.get("role") != "admin")}


def propose(db: Session, user: dict, goal: str) -> dict:
    """Plan only. No tool is run."""
    goal = goal.strip()
    live_intents = live_assistant.classify(goal) if user.get("role") != "volunteer" else []
    has_entities = live_retrieval.has_entities(live_retrieval.detect_entities(db, user, goal))
    route = adaptive.classify(goal, live_intents, has_entities)
    subs = decompose.decompose(goal, None)
    route_info = {"route": route["route"], "routes": route["routes"], "complexity": route["complexity"], "subquestions": [s["text"] for s in subs]}
    if route["route"] == "chitchat":
        return {"route": route_info, "plan": [], "planned_by": "rules"}
    plan, planned_by = planner.make_plan(db, user, goal, route, None)
    return {"route": route_info, "plan": [describe_step(i, p, user) for i, p in enumerate(plan)], "planned_by": planned_by}


def _run_step(db: Session, user: dict, tool, args: dict, create_proposals: bool) -> dict:
    is_admin = user.get("role") == "admin"
    args = dict(args)
    if tool.requires_approval:
        args["create_proposals"] = bool(create_proposals and is_admin)
    parsed = tool.input.model_validate(args)
    return tool.output.model_validate(tool.run(db, user, parsed)).model_dump()


def execute(db: Session, user: dict, goal: str, plan: list[dict], create_proposals: bool) -> Iterator[tuple[str, dict]]:
    """Yield (event, data). Events: step_start, step_done, then one `result` with everything to store."""
    t0 = time.time()
    is_admin = user.get("role") == "admin"
    steps: list[dict] = []
    warnings: list[str] = []
    if create_proposals and not is_admin:
        warnings.append("Only administrators can create proposals; none were created.")
    for i, p in enumerate(plan[: planner.MAX_STEPS]):
        tool = REGISTRY.get(p.get("tool"))
        yield "step_start", {"index": i, "tool": p.get("tool"), "why": p.get("why", ""), "kind": getattr(tool, "kind", None)}
        step = {"index": i, "tool": p.get("tool"), "kind": getattr(tool, "kind", None), "agent": AGENT_OF.get(getattr(tool, "kind", ""), "analyst"),
                "args": p.get("args") or {}, "why": p.get("why", ""), "requires_approval": bool(getattr(tool, "requires_approval", False)), "attempts": 0}
        s0 = time.time()
        if tool is None:
            step.update(status="error", error="Unknown tool.", output=None)
        elif tool.admin_only and not is_admin:
            step.update(status="denied", error="This tool is available to administrators only.", output=None)
        elif time.time() - t0 > TIME_BUDGET_SECONDS:
            step.update(status="skipped", error="The time budget for this run was used up before this step.", output=None)
        else:
            last_error = ""
            for attempt in (1, 2):
                step["attempts"] = attempt
                try:
                    step.update(status="ok", output=_clean(_run_step(db, user, tool, step["args"], create_proposals)), error=None)
                    break
                except ValidationError as exc:    # bad input or output: retrying cannot help
                    db.rollback()
                    step.update(status="error", output=None, error=f"input or output failed validation: {exc.errors()[0]['msg']}")
                    break
                except Exception as exc:
                    db.rollback()
                    last_error = str(exc)[:200] or type(exc).__name__
                    step.update(status="error", output=None, error=last_error)
                    if tool.requires_approval or time.time() - t0 > TIME_BUDGET_SECONDS:   # never repeat a step that may have written proposals
                        break
        step["ms"] = int((time.time() - s0) * 1000)
        steps.append(step)
        summary = explain_template([step])[:400] if step["status"] == "ok" else (step.get("error") or "")
        yield "step_done", {"index": i, "tool": step["tool"], "status": step["status"], "ms": step["ms"], "attempts": step["attempts"], "summary": summary,
                            "error": step.get("error")}

    # ---- verifier: the answer is built only from tool outputs, then every number is checked against them
    ok_steps = [s for s in steps if s["status"] == "ok"]
    allowed: list[float] = []
    for s in ok_steps:
        _numbers(s["output"], allowed)
        _numbers(s["args"], allowed)
    allowed += EXTRA_NUMBERS
    answer_text = explain_template(steps) if steps else GREETING
    rag = [s for s in ok_steps if s["tool"] == "retrieve_knowledge"]
    evidence = [e["text"] for s in rag for e in s["output"]["evidence"]] + [e["text"] for s in ok_steps if s["tool"] == "query_live_data" for e in s["output"]["evidence"]]
    numbers = ans.numbers_grounded(answer_text, evidence, allowed)
    violations = [v for s in ok_steps if s["tool"].startswith("optimize_") for v in s["output"]["violations"]]
    proposals = [pr for s in ok_steps if s["tool"].startswith("optimize_") for pr in s["output"]["proposals_created"]]
    if any(s["status"] == "denied" for s in steps):
        warnings.append("Some steps were skipped because they are available to administrators only.")
    if any(s["status"] == "skipped" for s in steps):
        warnings.append("The time budget ran out; remaining steps were not run.")
    failed = [s for s in steps if s["status"] in ("error", "denied", "skipped")]
    status = "failed" if steps and not ok_steps else "completed"
    validation = {"numbers_ok": numbers["ok"], "ungrounded": numbers["ungrounded"][:6], "constraints_ok": not violations,
                  "steps_ok": len(ok_steps), "steps_failed": len(failed), "warnings": warnings}
    yield "result", {"status": status, "answer": answer_text, "steps": steps, "validation": validation, "proposals": proposals,
                     "citations": [c for s in rag for c in s["output"]["citations"]], "duration_ms": int((time.time() - t0) * 1000)}


def report_markdown(run: dict) -> str:
    """A downloadable record of one run, built only from the stored, verified results."""
    lines = ["# CareBridge AI agent report", "", f"**Goal:** {run['goal']}", f"**Status:** {run['status']}", f"**Run:** #{run['id']}  ·  **Date:** {run.get('created_at')}", ""]
    lines += ["## Result", "", run.get("answer") or "_No answer was produced._", ""]
    lines += ["## Steps", ""]
    for s in run.get("steps") or []:
        lines.append(f"{s['index'] + 1}. **{s['tool']}** — {s['status']} ({s.get('ms', 0)} ms)")
        if s.get("why"):
            lines.append(f"   - Why: {s['why']}")
        if s.get("error"):
            lines.append(f"   - Note: {s['error']}")
    v = run.get("validation") or {}
    lines += ["", "## Verification", "", f"- Numbers traced to tool results: {'yes' if v.get('numbers_ok', True) else 'NO — ' + ', '.join(map(str, v.get('ungrounded', [])))}",
              f"- Constraints respected: {'yes' if v.get('constraints_ok', True) else 'no'}"]
    for w in v.get("warnings", []):
        lines.append(f"- Warning: {w}")
    lines += ["", "_Generated by CareBridge AI. Recommendations only; an administrator decides._"]
    return "\n".join(lines)
