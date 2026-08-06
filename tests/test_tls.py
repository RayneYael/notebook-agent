import os
import ssl

import pytest

from app.tls import TLSConfigurationError, configure_trusted_ca


def test_configure_trusted_ca_uses_certifi_and_keeps_verification_enabled(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    trusted = configure_trusted_ca()

    assert trusted.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert trusted.ssl_context.check_hostname is True
    assert trusted.bundle_path == os.environ["SSL_CERT_FILE"]
    assert trusted.bundle_path == os.environ["REQUESTS_CA_BUNDLE"]


def test_configure_trusted_ca_rejects_unreadable_explicit_bundle(tmp_path):
    with pytest.raises(TLSConfigurationError, match="readable file"):
        configure_trusted_ca(str(tmp_path / "missing.pem"))
