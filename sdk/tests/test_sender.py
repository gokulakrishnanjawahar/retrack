"""Background sender: async, bounded, retries, and never raises."""

import json
import threading

import httpx

from retrack.sender import BackgroundSender


def make_sender(handler, **kwargs) -> BackgroundSender:
    kwargs.setdefault("backoff_seconds", 0.01)
    return BackgroundSender(
        base_url="https://retrack.test",
        api_key="rtk_test_" + "0" * 48,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_posts_run_with_api_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(202, json={"duplicate": False})

    sender = make_sender(handler)
    sender.submit({"id": "r1"})
    assert sender.flush(timeout=2)
    assert seen[0].url == "https://retrack.test/v1/runs"
    assert seen[0].headers["authorization"] == "Bearer rtk_test_" + "0" * 48
    assert json.loads(seen[0].content) == {"id": "r1"}


def test_retries_server_errors_then_succeeds():
    responses = iter([503, 500, 202])
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(next(responses))

    sender = make_sender(handler)
    sender.submit({"id": "r1"})
    assert sender.flush(timeout=2)
    assert len(calls) == 3


def test_does_not_retry_rejected_runs():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(422, json={"error": {"code": "invalid_request"}})

    sender = make_sender(handler)
    sender.submit({"id": "r1"})
    assert sender.flush(timeout=2)
    assert len(calls) == 1


def test_server_down_never_raises_and_gives_up():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    sender = make_sender(handler, max_attempts=3)
    sender.submit({"id": "r1"})
    assert sender.flush(timeout=2)
    assert len(calls) == 3


def test_buffer_is_bounded_and_drops_oldest():
    release = threading.Event()
    sent = []

    def handler(request):
        release.wait(timeout=2)
        sent.append(json.loads(request.content)["id"])
        return httpx.Response(202)

    sender = make_sender(handler, max_buffer=3)
    for i in range(10):
        sender.submit({"id": i})
    assert sender.buffered <= 3
    assert sender.dropped >= 6
    release.set()
    assert sender.flush(timeout=2)
    assert sent[-3:] == [7, 8, 9]


def test_submit_after_close_is_ignored():
    sender = make_sender(lambda request: httpx.Response(202))
    sender.close(timeout=1)
    sender.submit({"id": "late"})
    assert sender.buffered == 0
