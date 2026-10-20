"""Known-fix recovery and circuit breaker for tools (Phase 11).

`memory.protect(tools)` wraps tools so that when one fails:
  * a failure Retrack knows a fix for comes back with the fix attached ("known_fix" on a
    returned error, KnownFailureError on a raised one), so the agent can apply it
    instead of retrying blindly;
  * a failure Retrack knows is unrecoverable, or the same failure repeating
    `max_same_failure` times, raises UnrecoverableToolError to stop wasting tokens.

Fingerprints must match the server's exactly (shared test vectors keep them in step).
"""

import hashlib
from collections import Counter
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, ToolException

from retrack.capture import reported_error


class UnrecoverableToolError(RuntimeError):
    """Retrying this tool call will not help; stop and handle it."""


class KnownFailureError(ToolException):
    """A known failure; the message includes the fix Retrack learned for it."""


def _type_shape(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + input_shape(value) + "}"
    if isinstance(value, list):
        return "[" + (_type_shape(value[0]) if value else "") + "]"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    return "str"


def input_shape(value: Any) -> str:
    """Keys and value types of tool arguments, never the values themselves."""
    if isinstance(value, dict):
        return ",".join(f"{key}:{_type_shape(value[key])}" for key in sorted(value))
    return _type_shape(value)


def fingerprint(tool_name: str, error_class: str, args: Any) -> str:
    raw = f"{tool_name}|{error_class}|{input_shape(args or {})}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _call(tool: BaseTool, args: dict[str, Any]) -> Any:
    # Call the underlying function so the wrapper, not the inner tool, is captured once.
    func = getattr(tool, "func", None)
    return func(**args) if func is not None else tool.invoke(args)


def protect_tools(
    tools: list[BaseTool], warnings: list[dict[str, Any]], max_same_failure: int = 3
) -> list[BaseTool]:
    known = {w.get("fingerprint"): w for w in warnings if w.get("fingerprint")}
    seen: Counter[str] = Counter()

    def wrap(tool: BaseTool) -> BaseTool:
        def on_failure(error_class: str, args: dict[str, Any]) -> str | None:
            digest = fingerprint(tool.name, error_class, args)
            seen[digest] += 1
            warning = known.get(digest, {})
            if warning.get("unrecoverable"):
                raise UnrecoverableToolError(
                    f"{tool.name} failed with {error_class}; Retrack knows retrying will not help"
                )
            if seen[digest] >= max_same_failure:
                raise UnrecoverableToolError(
                    f"{tool.name} failed with {error_class} {seen[digest]} times in this run;"
                    " stopping retries"
                )
            return warning.get("recovery")

        def run(**args: Any) -> Any:
            try:
                result = _call(tool, args)
            except UnrecoverableToolError:
                raise
            except Exception as exc:
                fix = on_failure(type(exc).__name__, args)
                if fix:
                    raise KnownFailureError(f"{exc}. Known fix from Retrack: {fix}") from exc
                raise
            if reported_error(result):
                fix = on_failure("ReportedError", args)
                if fix and isinstance(result, dict):
                    return {**result, "known_fix": fix}
            return result

        return StructuredTool.from_function(
            func=run, name=tool.name, description=tool.description, args_schema=tool.args_schema
        )

    return [wrap(tool) for tool in tools]


__all__ = [
    "KnownFailureError",
    "UnrecoverableToolError",
    "fingerprint",
    "input_shape",
    "protect_tools",
]
