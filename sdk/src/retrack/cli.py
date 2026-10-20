"""`retrack test`: run regression cases from Retrack's memory against your agent.

    retrack test --entry my_agent:run_task --agent support-agent --threshold 0.9

The entry point is a function `run_task(task: str, callbacks: list) -> str` that runs
your agent once and passes `callbacks` to it (config={"callbacks": callbacks}), so the
tools it calls can be checked. Runs made here are never sent as runs: only pass/fail
results go back to Retrack. Exit code 0 = passed, 1 = regression or pass rate below
the threshold, 2 = usage or connection error.
"""

import argparse
import importlib
import os
import sys
import uuid
from typing import Any

import httpx

from retrack.capture import RetrackCallbackHandler
from retrack.evals import check


def _load_entry(spec: str):
    module_name, _, function_name = spec.partition(":")
    if not module_name or not function_name:
        raise ValueError("--entry must look like module:function")
    sys.path.insert(0, os.getcwd())
    return getattr(importlib.import_module(module_name), function_name)


def _run_case(entry, agent: str, case: dict[str, Any]) -> dict[str, Any]:
    captured: list[dict[str, Any]] = []
    handler = RetrackCallbackHandler(captured.append, agent=agent)
    completed, output = True, None
    try:
        result = entry(case["input"].get("task", ""), [handler])
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
    return {"case_id": case["id"], "passed": not failures, "details": {"failures": failures}}


def _test(args, transport) -> int:
    try:
        entry = _load_entry(args.entry)
    except Exception as exc:
        print(f"retrack test: cannot load entry point {args.entry!r}: {exc}")
        return 2
    api_key = args.api_key or os.environ.get("RETRACK_API_KEY")
    base_url = args.base_url or os.environ.get("RETRACK_BASE_URL")
    if not api_key or not base_url:
        print("retrack test: set RETRACK_API_KEY and RETRACK_BASE_URL (or pass the options)")
        return 2
    client = httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
        transport=transport,
    )
    try:
        response = client.get("/v1/eval-cases", params={"agent": args.agent})
        response.raise_for_status()
        cases = response.json()["cases"]
        if not cases:
            print("No eval cases yet: Retrack creates them as playbooks become active.")
            return 0

        results = [_run_case(entry, args.agent, case) for case in cases]
        client.post(
            "/v1/eval-results",
            json={"test_run_id": str(uuid.uuid4()), "model_id": args.model_id, "results": results},
        ).raise_for_status()
    except httpx.HTTPError as exc:
        print(f"retrack test: could not reach Retrack: {exc}")
        return 2
    finally:
        client.close()

    passed = sum(r["passed"] for r in results)
    regressions = [
        case["id"]
        for case, result in zip(cases, results, strict=True)
        if case.get("critical") and case.get("last_result") == "passed" and not result["passed"]
    ]
    for case, result in zip(cases, results, strict=True):
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark} {case['source']:8} {case['input'].get('task', '')[:70]}")
        for failure in result["details"]["failures"]:
            print(f"     - {failure}")
    rate = passed / len(results)
    print(f"\n{passed}/{len(results)} passed ({rate:.0%}); threshold {args.threshold:.0%}")
    if regressions:
        print(f"REGRESSION: {len(regressions)} critical case(s) that passed before now fail")
    return 1 if regressions or rate < args.threshold else 0


def main(argv: list[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retrack")
    commands = parser.add_subparsers(dest="command", required=True)
    test = commands.add_parser("test", help="run regression cases from Retrack's memory")
    test.add_argument("--entry", required=True, help="module:function that runs one task")
    test.add_argument("--agent", required=True, help="agent name used with Retrack")
    test.add_argument("--threshold", type=float, default=0.9, help="minimum pass rate")
    test.add_argument("--model-id", default=None, help="model under test (recorded)")
    test.add_argument("--api-key", default=None)
    test.add_argument("--base-url", default=None)
    args = parser.parse_args(argv)
    return _test(args, transport)


if __name__ == "__main__":
    sys.exit(main())
