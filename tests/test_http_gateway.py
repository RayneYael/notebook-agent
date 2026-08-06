import time
from uuid import uuid4

from app.channels.http_gateway import RequestVerifier, signature


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
