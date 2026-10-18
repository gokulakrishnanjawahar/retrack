"""Sends captured runs to Retrack on a background thread.

Never raises into the caller. The buffer is bounded: when it is full the oldest
run is dropped, so a Retrack outage can never grow the agent's memory use.
"""

import logging
import threading
import time
from collections import deque
from typing import Any

import httpx

logger = logging.getLogger("retrack")


class BackgroundSender:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        max_buffer: int = 1000,
        max_attempts: int = 5,
        backoff_seconds: float = 0.5,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._buffer: deque[tuple[str, dict[str, Any]]] = deque(maxlen=max_buffer)
        self._cond = threading.Condition()
        self._in_flight = False
        self._closed = False
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self.dropped = 0
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
            transport=transport,
        )
        self._thread = threading.Thread(target=self._run, name="retrack-sender", daemon=True)
        self._thread.start()

    @property
    def buffered(self) -> int:
        return len(self._buffer)

    def submit(self, payload: dict[str, Any], path: str = "/v1/runs") -> None:
        with self._cond:
            if self._closed:
                return
            if len(self._buffer) == self._buffer.maxlen:
                self.dropped += 1
                logger.warning("retrack: buffer full, dropping oldest run")
            self._buffer.append((path, payload))
            self._cond.notify_all()

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until every buffered run is sent or given up. False on timeout."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._buffer or self._in_flight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
        return True

    def close(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        with self._cond:
            self._closed = True
            self._buffer.clear()
            self._cond.notify_all()
        self._thread.join(timeout=1.0)
        self._client.close()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._buffer and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                path, payload = self._buffer.popleft()
                self._in_flight = True
            try:
                self._send(path, payload)
            except Exception:  # never let the sender thread die
                logger.exception("retrack: unexpected error sending run")
            finally:
                with self._cond:
                    self._in_flight = False
                    self._cond.notify_all()

    def _send(self, path: str, payload: dict[str, Any]) -> None:
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(path, json=payload)
            except httpx.HTTPError as exc:
                logger.debug("retrack: send failed (%s)", exc)
            else:
                if response.status_code < 400:
                    return
                if response.status_code != 429 and response.status_code < 500:
                    logger.warning(
                        "retrack: %s for %s rejected (%s): %s",
                        path,
                        payload.get("id") or payload.get("run_id"),
                        response.status_code,
                        response.text[:500],
                    )
                    return
            if attempt + 1 < self._max_attempts:
                time.sleep(self._backoff * 2**attempt)
        logger.warning(
            "retrack: giving up on %s for %s", path, payload.get("id") or payload.get("run_id")
        )
