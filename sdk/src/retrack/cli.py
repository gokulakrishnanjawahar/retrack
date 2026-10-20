"""Retrack command line: regression tests and model migrations from Retrack's memory.

    retrack test    --entry my_agent:run_task --agent support-agent [--threshold 0.9]
    retrack migrate --to new-model --entry my_agent:run_task --agent support-agent

The entry point runs your agent once: `run_task(task, callbacks)` or, to let Retrack
choose the model, `run_task(task, callbacks, model_id)`. Pass `callbacks` to your agent
(config={"callbacks": callbacks}) so the tools it calls can be checked. Runs made here
are never sent as runs: only pass/fail results go back to Retrack.

Exit codes: 0 passed; 1 regression, pass rate below the threshold, or (migrate) a
playbook breaks or a known failure returns; 2 usage or connection error.
"""

import argparse
import importlib
import inspect
import os
import random
import sys
import uuid
from collections.abc import Callable
from typing import Any

import httpx

from retrack.capture import RetrackCallbackHandler
from retrack.evals import check


class UsageError(Exception):
    pass


def _load_entry(spec: str) -> Callable[..., Any]:
    module_name, _, function_name = spec.partition(":")
    if not module_name or not function_name:
        raise UsageError("--entry must look like module:function")
    sys.path.insert(0, os.getcwd())
    try:
        return getattr(importlib.import_module(module_name), function_name)
    except Exception as exc:
        raise UsageError(f"cannot load entry point {spec!r}: {exc}") from exc


def _accepts_model(entry: Callable[..., Any]) -> bool:
    """True when the entry can take a third positional argument (the model id)."""
    try:
        params = inspect.signature(entry).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return len(positional) >= 3 or any(p.kind == p.VAR_POSITIONAL for p in params)


def _client(args, transport) -> httpx.Client:
    api_key = args.api_key or os.environ.get("RETRACK_API_KEY")
    base_url = args.base_url or os.environ.get("RETRACK_BASE_URL")
    if not api_key or not base_url:
        raise UsageError("set RETRACK_API_KEY and RETRACK_BASE_URL (or pass the options)")
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
        transport=transport,
    )


def _run_case(entry, agent: str, case: dict[str, Any], model_id: str | None) -> dict[str, Any]:
    captured: list[dict[str, Any]] = []
    handler = RetrackCallbackHandler(captured.append, agent=agent)
    task = case["input"].get("task", "")
    completed, output = True, None
    try:
        if model_id is not None and _accepts_model(entry):
            result = entry(task, [handler], model_id)
        else:
            result = entry(task, [handler])
        output = result if isinstance(result, str) else None
    except Exception:
        completed = False
    run = captured[-1] if captured else {"steps": [], "output": None}
    failures = check(
        case.get("assertions") or [],
        completed=completed,
        steps=run.get("steps") or [],
        output=output or run.get("output"),
    )
    return {
        "case_id": case["id"],
        "passed": not failures,
        "details": {"failures": failures, "completed": completed},
    }


def _fetch_cases(client: httpx.Client, agent: str) -> list[dict[str, Any]]:
    response = client.get("/v1/eval-cases", params={"agent": agent})
    response.raise_for_status()
    return response.json()["cases"]


def _print_cases(cases, results) -> None:
    for case, result in zip(cases, results, strict=True):
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark} {case['source']:8} {case['input'].get('task', '')[:70]}")
        for failure in result["details"]["failures"]:
            print(f"     - {failure}")


def _test(args, client: httpx.Client) -> int:
    entry = _load_entry(args.entry)
    cases = _fetch_cases(client, args.agent)
    if not cases:
        print("No eval cases yet: Retrack creates them as playbooks become active.")
        return 0
    results = [_run_case(entry, args.agent, case, args.model_id) for case in cases]
    client.post(
        "/v1/eval-results",
        json={"test_run_id": str(uuid.uuid4()), "model_id": args.model_id, "results": results},
    ).raise_for_status()

    _print_cases(cases, results)
    passed = sum(r["passed"] for r in results)
    regressions = [
        case["id"]
        for case, result in zip(cases, results, strict=True)
        if case.get("critical") and case.get("last_result") == "passed" and not result["passed"]
    ]
    rate = passed / len(results)
    print(f"\n{passed}/{len(results)} passed ({rate:.0%}); threshold {args.threshold:.0%}")
    if regressions:
        print(f"REGRESSION: {len(regressions)} critical case(s) that passed before now fail")
    return 1 if regressions or rate < args.threshold else 0


def _migrate(args, client: httpx.Client) -> int:
    entry = _load_entry(args.entry)
    model_applied = _accepts_model(entry)
    if not model_applied:
        print(
            f"WARNING: {args.entry} takes no model_id argument, so the replay may not use "
            f"{args.to}. Add a third parameter: run_task(task, callbacks, model_id)."
        )
    response = client.post(
        "/v1/migrations",
        json={
            "agent": args.agent,
            "to_model": args.to,
            "from_model": args.from_model,
            "model_applied": model_applied,
        },
    )
    response.raise_for_status()
    migration_id = response.json()["id"]

    cases = _fetch_cases(client, args.agent)
    if args.sample and args.sample < len(cases):
        cases = random.Random(args.seed).sample(cases, args.sample)
    if not cases:
        print("No eval cases yet: nothing to replay.")
        return 0
    results = [_run_case(entry, args.agent, case, args.to) for case in cases]
    client.post(
        "/v1/eval-results",
        json={
            "test_run_id": str(uuid.uuid4()),
            "model_id": args.to,
            "migration_id": migration_id,
            "results": results,
        },
    ).raise_for_status()
    report = client.get(f"/v1/migrations/{migration_id}")
    report.raise_for_status()
    summary = report.json()["summary"]

    counts = summary.get("counts", {})
    print(f"Model migration to {args.to} ({len(results)} cases replayed)\n")
    for item in summary.get("items", []):
        print(f"{item['result']:17} {item['title']}")
        for failure in item.get("failures") or []:
            print(f"     - {failure}")
    print("\n" + ", ".join(f"{key}: {value}" for key, value in counts.items()))
    blocked = counts.get("breaks", 0) + counts.get("returns", 0)
    if blocked:
        print(f"NOT READY: {blocked} item(s) break or fail again on {args.to}")
    return 1 if blocked else 0


def main(argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retrack")
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub):
        sub.add_argument("--entry", required=True, help="module:function that runs one task")
        sub.add_argument("--agent", required=True, help="agent name used with Retrack")
        sub.add_argument("--api-key", default=None)
        sub.add_argument("--base-url", default=None)

    test = commands.add_parser("test", help="run regression cases from Retrack's memory")
    common(test)
    test.add_argument("--threshold", type=float, default=0.9, help="minimum pass rate")
    test.add_argument("--model-id", default=None, help="model under test (recorded)")

    migrate = commands.add_parser("migrate", help="replay memory on a new model and report")
    common(migrate)
    migrate.add_argument("--to", required=True, help="the model to migrate to")
    migrate.add_argument("--from", dest="from_model", default=None, help="the current model")
    migrate.add_argument("--sample", type=int, default=None, help="replay only N cases")
    migrate.add_argument("--seed", type=int, default=0, help="seed for --sample")

    args = parser.parse_args(argv)
    try:
        with _client(args, transport) as client:
            return (_test if args.command == "test" else _migrate)(args, client)
    except UsageError as exc:
        print(f"retrack {args.command}: {exc}")
        return 2
    except httpx.HTTPError as exc:
        print(f"retrack {args.command}: could not reach Retrack: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
