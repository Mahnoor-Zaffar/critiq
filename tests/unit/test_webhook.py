import hashlib
import hmac

from critiq.integrations.github.webhook import verify_signature


def _sig(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_verify_signature_valid():
    payload = b'{"action":"opened"}'
    assert verify_signature(payload, _sig(payload, "secret"), "secret") is True


def test_verify_signature_invalid():
    payload = b'{"action":"opened"}'
    assert verify_signature(payload, "sha256=" + "0" * 64, "secret") is False


def test_verify_signature_bad_prefix():
    assert verify_signature(b"x", "not-sha256", "secret") is False
