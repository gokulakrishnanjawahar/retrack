"""The Retrack client: the one object an agent developer creates."""

import atexit
import logging
import os
from collections.abc import Iterable
from typing import Any

import httpx

from retrack.capture import RetrackCallbackHandler
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
