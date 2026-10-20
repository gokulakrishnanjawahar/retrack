"""The Retrack client: the one object an agent developer creates."""

import atexit
import concurrent.futures
import logging
import os
from collections.abc import Callable, Iterable
from typing import Any

import httpx

from retrack.capture import RetrackCallbackHandler
from retrack.memory import Memory
from retrack.redact import redact_secrets
from retrack.sender import BackgroundSender

logger = logging.getLogger("retrack")


class Retrack:
    """Capture agent runs and send them to Retrack.

    Missing configuration never breaks the agent: without an API key or base URL,
    capture is disabled and a warning is logged.

        rt = Retrack(agent="support-agent")  # reads RETRACK_API_KEY, RETRACK_BASE_URL
        graph.invoke(inputs, config={"callbacks": [rt.callback()]})
    """

    def __init__(
        self,
        agent: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model_id: str | None = None,
        tool_versions: dict[str, str] | None = None,
        trusted_tools: Iterable[str] = (),
        max_buffer: int = 1000,
        transport: httpx.BaseTransport | None = None,
    ):
        self.agent = agent
        self._model_id = model_id
        self._tool_versions = dict(tool_versions or {})
        self._trusted_tools = frozenset(trusted_tools)
        self._sender: BackgroundSender | None = None
        self._recall_client: httpx.Client | None = None
        self._recall_pool: concurrent.futures.ThreadPoolExecutor | None = None

        api_key = api_key or os.environ.get("RETRACK_API_KEY")
        base_url = base_url or os.environ.get("RETRACK_BASE_URL")
        if not api_key or not base_url:
            logger.warning("retrack: RETRACK_API_KEY or RETRACK_BASE_URL not set; capture disabled")
            return
        try:
            self._sender = BackgroundSender(
                base_url, api_key, max_buffer=max_buffer, transport=transport
            )
            atexit.register(self._sender.flush, 2.0)
            self._recall_client = httpx.Client(
                base_url=base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {api_key}"},
                transport=transport,
            )
            self._recall_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="retrack-recall"
            )
        except Exception:
            logger.exception("retrack: could not start sender; capture disabled")

    def callback(
        self, task: str | None = None, output_key: str | None = None
    ) -> RetrackCallbackHandler:
        """A LangChain/LangGraph callback handler.

        `task` overrides the task text derived from the inputs; `output_key` names the
        graph-state field holding the final answer (default: the last AI message).
        """
        return RetrackCallbackHandler(
            self._submit,
            agent=self.agent,
            task=task,
            model_id=self._model_id,
            tool_versions=self._tool_versions,
            trusted_tools=self._trusted_tools,
            output_key=output_key,
        )

    def recall(
        self,
        task: str,
        *,
        run_id: Any = None,
        model_id: str | None = None,
        tool_versions: dict[str, str] | None = None,
        max_playbooks: int = 3,
        timeout: float = 0.4,
    ) -> Memory:
        """Memory for the task the agent is about to do. Never raises and never blocks
        longer than `timeout` seconds: on any problem it returns empty memory.

        Pass the same `run_id` you give the graph (config={"run_id": ...}) so Retrack can
        learn which recalled playbooks helped.
        """
        if self._recall_client is None or self._recall_pool is None:
            return Memory()
        try:
            body = {
                "agent": self.agent,
                "task": redact_secrets(task),
                "model_id": model_id or self._model_id,
                "tool_versions": tool_versions
                if tool_versions is not None
                else self._tool_versions,
                "max_playbooks": max_playbooks,
            }
            if run_id is not None:
                body["run_id"] = str(run_id)
            future = self._recall_pool.submit(
                self._recall_client.post, "/v1/recall", json=body, timeout=timeout
            )
            response = future.result(timeout=timeout)
            if response.status_code != 200:
                logger.warning("retrack: recall failed (%s)", response.status_code)
                return Memory()
            return Memory.from_response(response.json())
        except Exception as exc:
            logger.warning("retrack: recall skipped (%s)", type(exc).__name__)
            return Memory()

    def recall_node(
        self, task_key: str = "task", into: str = "retrack_memory"
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """A LangGraph node that recalls memory for state[task_key] into state[into].

        Uses state["run_id"] when present to link the recall to the run.
        """

        def node(state: dict[str, Any]) -> dict[str, Any]:
            task = state.get(task_key) if isinstance(state, dict) else None
            if not task:
                return {into: ""}
            memory = self.recall(str(task), run_id=state.get("run_id"))
            return {into: memory.as_prompt()}

        return node

    def feedback(
        self,
        run_id: Any,
        *,
        outcome: str,
        source: str = "feedback",
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Report a run's outcome later: `source` is "test", "event" or "feedback".

        Safest: choose the run id yourself and pass it to the graph, then use it here:

            run_id = uuid.uuid4()
            graph.invoke(inputs, config={"callbacks": [handler], "run_id": run_id})
            rt.feedback(run_id, outcome="success", source="test")

        `handler.last_run_id` also works when a handler runs one graph at a time. Sent in
        the background like runs; never raises.
        """
        try:
            payload = {
                "run_id": str(run_id),
                "outcome": outcome,
                "source": source,
                "detail": redact_secrets(detail or {}),
            }
            if self._sender:
                self._sender.submit(payload, path="/v1/feedback")
        except Exception:
            logger.exception("retrack: could not queue feedback")

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until captured runs are sent. Returns False on timeout."""
        return self._sender.flush(timeout) if self._sender else True

    def close(self, timeout: float = 5.0) -> None:
        if self._sender:
            self._sender.close(timeout)

    def _submit(self, payload: dict[str, Any]) -> None:
        if self._sender:
            self._sender.submit(payload)
