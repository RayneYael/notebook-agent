import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from uuid import uuid4

from app.agent.types import AgentAnswer
from app.channels.http_gateway import RequestVerifier, _handler, signature


def test_gateway_signature_accepts_once_and_rejects_replay_or_tampering():
    secret = "s" * 32
    body = b'{"channel":"telegram"}'
    timestamp = str(int(time.time()))
    nonce = uuid4().hex
    signed = signature(secret, body, timestamp, nonce)
    verifier = RequestVerifier(secret)

    assert verifier.verify(body, timestamp, nonce, signed)
    assert not verifier.verify(body, timestamp, nonce, signed)
    assert not verifier.verify(body + b" ", timestamp, uuid4().hex, signed)


def test_gateway_rejects_stale_requests_and_short_secrets():
    secret = "s" * 32
    body = b"{}"
    timestamp = str(int(time.time()) - 120)
    nonce = uuid4().hex
    verifier = RequestVerifier(secret)

    assert not verifier.verify(body, timestamp, nonce, signature(secret, body, timestamp, nonce))

    try:
        RequestVerifier("short")
    except ValueError as exc:
        assert "at least 32" in str(exc)
    else:
        raise AssertionError("short gateway secret should be rejected")


def test_gateway_replaces_untrusted_request_id_at_the_http_boundary():
    secret = "s" * 32
    received = []

    def dispatch(envelope):
        received.append(envelope)
        return AgentAnswer(status="ok", text="safe")

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler(RequestVerifier(secret), dispatch)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "channel": "telegram",
                "account_id": "account",
                "external_user_id": "external-user",
                "conversation_id": "conversation",
                "message_id": "message",
                "text": "private message body",
                "request_id": "attacker-chosen-id",
            }
        ).encode()
        timestamp = str(int(time.time()))
        nonce = uuid4().hex
        request = Request(
            f"http://127.0.0.1:{server.server_port}/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-KB-Timestamp": timestamp,
                "X-KB-Nonce": nonce,
                "X-KB-Signature": signature(secret, body, timestamp, nonce),
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert received[0].request_id != "attacker-chosen-id"
    assert len(received[0].request_id) == 32
