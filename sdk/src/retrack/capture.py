"""LangGraph / LangChain callback that records each agent run as a Retrack run.

The outermost chain of an invocation (for LangGraph, the graph itself) is one run;
its LangChain run id becomes the Retrack run id. Every LLM call and tool call inside
it becomes a step. Callback errors are logged and swallowed, never raised.
"""

import functools
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from retrack.redact import redact_secrets

logger = logging.getLogger("retrack")

MAX_STEPS = 500
MAX_TASK_CHARS = 50_000
MAX_OUTPUT_CHARS = 4000
_TASK_KEYS = ("task", "input", "question", "query")


def _safe(method: Callable) -> Callable:
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            logger.exception("retrack: capture error in %s", method.__name__)

    return wrapper


@dataclass
class _Step:
    idx: int
    type: str
    started: float
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Run:
    id: UUID
    task: str
    started: float
    output: str | None = None
    model_id: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    next_idx: int = 0
    open_steps: dict[UUID, _Step] = field(default_factory=dict)
    steps: list[_Step] = field(default_factory=list)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _message_text(message: Any) -> tuple[str | None, str | None]:
    """Return (role, text) for a LangChain message, (role, text) tuple or dict."""
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[0]), str(message[1])
    if isinstance(message, dict):
        return message.get("role") or message.get("type"), message.get("content")
    content = getattr(message, "content", None)
    if isinstance(content, list):
        content = " ".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return getattr(message, "type", None), content


def derive_task(inputs: Any) -> str:
    """Best-effort task text from graph inputs: last human message, else a common key."""
    if isinstance(inputs, dict):
        for message in reversed(inputs.get("messages") or []):
            role, text = _message_text(message)
            if role in ("human", "user") and text:
                return str(text)
        for key in _TASK_KEYS:
            if isinstance(inputs.get(key), str) and inputs[key]:
                return inputs[key]
    elif isinstance(inputs, str) and inputs:
        return inputs
    text = json.dumps(_json_safe(inputs))[:2000]
    return text if text not in ("", "null", "{}") else "(unknown task)"


def extract_output(outputs: Any, output_key: str | None) -> str | None:
    """The run's final answer: a chosen state field, else the last AI message, else the outputs."""
    value: Any = outputs
    if isinstance(outputs, dict):
        if output_key is not None:
            value = outputs.get(output_key)
        else:
            for message in reversed(outputs.get("messages") or []):
                role, text = _message_text(message)
                if role in ("ai", "assistant") and text:
                    value = text
                    break
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(_json_safe(value))
    return redact_secrets(text)[:MAX_OUTPUT_CHARS] or None


def _llm_usage(response: Any) -> tuple[int | None, int | None, str | None]:
    tokens_in = tokens_out = model = None
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None) or {}
            if usage:
                tokens_in = (tokens_in or 0) + usage.get("input_tokens", 0)
                tokens_out = (tokens_out or 0) + usage.get("output_tokens", 0)
            metadata = getattr(message, "response_metadata", None) or {}
            model = model or metadata.get("model_name") or metadata.get("model")
    llm_output = getattr(response, "llm_output", None) or {}
    model = model or llm_output.get("model_name") or llm_output.get("model")
    if tokens_in is None and isinstance(llm_output.get("token_usage"), dict):
        usage = llm_output["token_usage"]
        tokens_in, tokens_out = usage.get("prompt_tokens"), usage.get("completion_tokens")
    return tokens_in, tokens_out, model


class RetrackCallbackHandler(BaseCallbackHandler):
    raise_error = False

    def __init__(
        self,
        submit: Callable[[dict[str, Any]], None],
        *,
        agent: str,
        task: str | None = None,
        model_id: str | None = None,
        tool_versions: dict[str, str] | None = None,
        trusted_tools: frozenset[str] = frozenset(),
        output_key: str | None = None,
    ):
        self._submit = submit
        self._output_key = output_key
        self._agent = agent
        self._task = task
        self._model_id = model_id
        self._tool_versions = dict(tool_versions or {})
        self._trusted_tools = trusted_tools
        self._lock = threading.Lock()
        self._runs: dict[UUID, _Run] = {}
        self._root_of: dict[UUID, UUID] = {}
        # Most recent run started by this handler. With one handler shared across concurrent
        # runs, pass config={"run_id": ...} instead and use that id.
        self.last_run_id: UUID | None = None

    # Run boundaries -------------------------------------------------------------------

    def _start_child(self, run_id: UUID, parent_run_id: UUID | None) -> _Run | None:
        root = self._root_of.get(parent_run_id) if parent_run_id else None
        if root is None:
            return None
        self._root_of[run_id] = root
        return self._runs.get(root)

    @_safe
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        with self._lock:
            if parent_run_id is None:
                self.last_run_id = run_id
                task = self._task or derive_task(inputs)
                self._runs[run_id] = _Run(run_id, task[:MAX_TASK_CHARS], time.monotonic())
                self._root_of[run_id] = run_id
            else:
                self._start_child(run_id, parent_run_id)

    @_safe
    def on_chain_end(self, outputs, *, run_id, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            with self._lock:
                run = self._runs.get(run_id)
                if run is not None:
                    run.output = extract_output(outputs, self._output_key)
            self._finish(run_id)

    @_safe
    def on_chain_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            self._finish(run_id)

    def _finish(self, root_id: UUID) -> None:
        with self._lock:
            run = self._runs.pop(root_id, None)
            self._root_of = {k: v for k, v in self._root_of.items() if v != root_id}
        if run is None:
            return
        steps = sorted(run.steps, key=lambda s: s.idx)
        if len(steps) > MAX_STEPS:
            logger.warning(
                "retrack: run %s has %d steps; keeping %d", run.id, len(steps), MAX_STEPS
            )
            steps = steps[:MAX_STEPS]
        payload = {
            "id": str(run.id),
            "agent": self._agent,
            "task": redact_secrets(run.task),
            "model_id": self._model_id or run.model_id or "unknown",
            "tool_versions": self._tool_versions,
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
            "latency_ms": int((time.monotonic() - run.started) * 1000),
            **({"output": run.output} if run.output else {}),
            "steps": [{"idx": i, "type": step.type, **step.fields} for i, step in enumerate(steps)],
        }
        self._submit(payload)

    # Steps ----------------------------------------------------------------------------

    def _open_step(self, run_id, parent_run_id, step_type: str, **fields) -> None:
        with self._lock:
            run = self._start_child(run_id, parent_run_id)
            if run is None:
                return
            run.open_steps[run_id] = _Step(run.next_idx, step_type, time.monotonic(), fields)
            run.next_idx += 1

    def _close_step(self, run_id, **fields) -> None:
        with self._lock:
            root = self._root_of.get(run_id)
            run = self._runs.get(root) if root else None
            step = run.open_steps.pop(run_id, None) if run else None
            if step is None:
                return
            step.fields.update(fields)
            step.fields["latency_ms"] = int((time.monotonic() - step.started) * 1000)
            run.steps.append(step)
            if step.type == "llm":
                run.tokens_in += step.fields.get("tokens_in") or 0
                run.tokens_out += step.fields.get("tokens_out") or 0

    @_safe
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._open_step(run_id, parent_run_id, "llm", input_trust="untrusted")

    @_safe
    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        self._open_step(run_id, parent_run_id, "llm", input_trust="untrusted")

    @_safe
    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs):
        tokens_in, tokens_out, model = _llm_usage(response)
        with self._lock:
            root = self._root_of.get(run_id)
            run = self._runs.get(root) if root else None
            if run is not None and model and run.model_id is None:
                run.model_id = model
        self._close_step(run_id, result_class="ok", tokens_in=tokens_in, tokens_out=tokens_out)

    @_safe
    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._close_step(run_id, result_class="error", error_class=type(error).__name__)

    @_safe
    def on_tool_start(
        self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs
    ):
        name = (serialized or {}).get("name") or kwargs.get("name") or "unknown_tool"
        args = inputs if isinstance(inputs, dict) else {"input": input_str}
        trust = "trusted" if name in self._trusted_tools else "untrusted"
        self._open_step(
            run_id,
            parent_run_id,
            "tool",
            tool_name=name,
            args=redact_secrets(_json_safe(args)),
            input_trust=trust,
        )

    @_safe
    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        self._close_step(run_id, result_class="ok")

    @_safe
    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs):
        self._close_step(run_id, result_class="error", error_class=type(error).__name__)
