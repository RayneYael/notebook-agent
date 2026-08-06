"""Trusted CA-bundle resolution for outbound provider clients.

The application must never make provider calls with certificate verification
disabled.  Some macOS Python builds do not have a usable OpenSSL default CA
path, so the composition root resolves a readable bundle explicitly.
"""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from pathlib import Path

import certifi


class TLSConfigurationError(RuntimeError):
    """A configured CA bundle cannot be used safely."""


@dataclass(frozen=True)
class TrustedCA:
    """One verified CA bundle shared by every outbound provider client."""

    bundle_path: str
    ssl_context: ssl.SSLContext


def configure_trusted_ca(configured_bundle: str | None = None) -> TrustedCA:
    """Resolve a CA bundle and expose it to standard Python HTTP clients.

    An explicit deployment value wins.  In its absence, existing standard
    variables are respected, then certifi is used as the portable fallback.
    The resolved bundle is always passed directly to clients as well; setting
    the environment variables preserves compatibility with provider SDKs that
    construct their own clients.
    """

    candidate = (
        configured_bundle
        or os.environ.get("SSL_CERT_FILE")
        or os.environ.get("REQUESTS_CA_BUNDLE")
        or certifi.where()
    )
    path = Path(candidate).expanduser()
    if not path.is_file() or not os.access(path, os.R_OK):
        raise TLSConfigurationError("configured CA bundle is not a readable file")
    try:
        context = ssl.create_default_context(cafile=str(path))
    except (OSError, ssl.SSLError) as exc:
        raise TLSConfigurationError("configured CA bundle could not be loaded") from exc

    resolved = str(path)
    # Do not permit a later, implicit client to fall back to this Python
    # installation's missing default CA path.  Neither variable is a secret.
    os.environ["SSL_CERT_FILE"] = resolved
    os.environ["REQUESTS_CA_BUNDLE"] = resolved
    return TrustedCA(bundle_path=resolved, ssl_context=context)
