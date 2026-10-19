"""Memory firewall, core part (docs/firewall.md): taint tracking and the promotion rule.

Trust comes only from the project's settings (`trusted_tools`, `task_trusted`), never
from what the client claims. A run is trusted only when its task is trusted and every
step is trusted; anything else taints it. Redaction happens earlier, at ingest.
"""

from typing import Any, TypedDict
from uuid import UUID

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from psycopg.types.json import Jsonb

from retrack_server.db import project_scope, worker_scope

# Independent trusted successes needed before a candidate becomes active without a human.
REQUIRED_TRUSTED_SUCCESSES = 3


class FirewallState(TypedDict, total=False):
    project_id: UUID
    run_id: UUID
    trusted_tools: list[str]
    task_trusted: bool
    current_taint: str
    steps: list[tuple[int, str, str | None]]
    step_trust: dict[int, str]
    taint_level: str


def _conn(config: RunnableConfig) -> psycopg.Connection:
    return config["configurable"]["conn"]


def _load(state: FirewallState, config: RunnableConfig) -> dict[str, Any]:
    conn = _conn(config)
    with project_scope(conn, state["project_id"]):
        return _read(conn, state)


def _read(conn: psycopg.Connection, state: FirewallState) -> dict[str, Any]:
    project = conn.execute(
        "select trusted_tools, task_trusted from public.projects where id = %s",
        (state["project_id"],),
    ).fetchone()
    run = conn.execute(
        "select taint_level from public.runs where project_id = %s and id = %s",
        (state["project_id"], state["run_id"]),
    ).fetchone()
    if project is None or run is None:
        raise LookupError(f"run {state['run_id']} not found in project {state['project_id']}")
    steps = conn.execute(
        "select idx, type, tool_name from public.steps"
        " where project_id = %s and run_id = %s order by idx",
        (state["project_id"], state["run_id"]),
    ).fetchall()
    return {
        "trusted_tools": project[0],
        "task_trusted": project[1],
        "current_taint": run[0],
        "steps": steps,
    }


def _assess(state: FirewallState) -> dict[str, Any]:
    trusted_tools = set(state["trusted_tools"])
    trusted_so_far = state["task_trusted"]
    step_trust: dict[int, str] = {}
    for idx, step_type, tool_name in state["steps"]:
        # A tool step is trusted only if listed; an LLM step reads the task and every earlier step.
        trusted = tool_name in trusted_tools if step_type == "tool" else trusted_so_far
        step_trust[idx] = "trusted" if trusted else "untrusted"
        trusted_so_far = trusted_so_far and trusted
    if state["current_taint"] == "quarantined":
        taint = "quarantined"
    else:
        taint = "trusted" if trusted_so_far else "untrusted"
    return {"step_trust": step_trust, "taint_level": taint}


def _save(state: FirewallState, config: RunnableConfig) -> dict[str, Any]:
    # Only the worker role may write trust and processing state (least privilege).
    conn = _conn(config)
    with worker_scope(conn):
        conn.execute(
            "select private.record_firewall_result(%s, %s, %s, %s)",
            (
                state["project_id"],
                state["run_id"],
                state["taint_level"],
                Jsonb({str(idx): trust for idx, trust in state["step_trust"].items()}),
            ),
        )
    return {}


def _build_graph():
    graph = StateGraph(FirewallState)
    graph.add_node("load", _load)
    graph.add_node("assess", _assess)
    graph.add_node("save", _save)
    graph.add_edge(START, "load")
    graph.add_edge("load", "assess")
    graph.add_edge("assess", "save")
    graph.add_edge("save", END)
    return graph.compile()


_GRAPH = _build_graph()


def process_run(conn: psycopg.Connection, project_id: UUID, run_id: UUID) -> str:
    """Run the firewall on one stored run. Returns the run's taint level."""
    state = _GRAPH.invoke(
        {"project_id": project_id, "run_id": run_id}, config={"configurable": {"conn": conn}}
    )
    return state["taint_level"]


# Promotion rule (used by distillation, Phase 5) -------------------------------------------


def initial_status(source_taints: list[str]) -> str:
    """New or updated memory never starts active, whatever its sources."""
    return "candidate"


def needs_review(source_taints: list[str]) -> bool:
    """Memory from any untrusted or quarantined run goes to the review queue."""
    return any(taint != "trusted" for taint in source_taints)


def promotion_allowed(
    source_taints: list[str],
    *,
    human_approved: bool,
    trusted_successes: int,
    passed_automatic_checks: bool = False,
) -> bool:
    """Whether a candidate may become active (docs/firewall.md, rules 1-3)."""
    if not source_taints:
        return False
    if human_approved:
        return True
    if "quarantined" in source_taints:
        return False
    if needs_review(source_taints) and not passed_automatic_checks:
        return False
    return trusted_successes >= REQUIRED_TRUSTED_SUCCESSES
