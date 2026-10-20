"""Checks for regression cases generated from Retrack's memory."""

from typing import Any


def _tool_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in steps if s.get("type") == "tool"]


def check(
    assertions: list[dict[str, Any]],
    *,
    completed: bool,
    steps: list[dict[str, Any]],
    output: str | None,
) -> list[str]:
    """Failure messages for a case; an empty list means it passed.

    Unknown assertion types (for example AI-judged criteria, not supported yet) are
    skipped rather than failed, so newer servers never break older SDKs.
    """
    failures = []
    tools_called = [s.get("tool_name") for s in _tool_steps(steps)]
    for assertion in assertions:
        kind = assertion.get("type")
        if kind == "completes" and not completed:
            failures.append("the agent raised an error")
        elif kind == "tool_sequence":
            expected = list(assertion.get("tools") or [])
            remaining = iter(tools_called)
            if not all(tool in remaining for tool in expected):
                failures.append(
                    f"expected tools in order: {' -> '.join(expected)};"
                    f" called: {', '.join(t or '?' for t in tools_called) or 'none'}"
                )
        elif kind == "no_failure":
            tool, error = assertion.get("tool"), assertion.get("error_class")
            if any(
                s.get("tool_name") == tool and s.get("error_class") == error
                for s in _tool_steps(steps)
            ):
                failures.append(f"{tool} failed with {error} again")
        elif kind == "output_contains":
            value = str(assertion.get("value", ""))
            if value not in (output or ""):
                failures.append(f"output does not contain {value!r}")
    return failures
