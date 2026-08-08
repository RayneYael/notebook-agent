"""Public Vercel health endpoint for the competition environment."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

from app.deployment_health import build_health_response


class handler(BaseHTTPRequestHandler):
    """Vercel-compatible request handler."""

    def do_GET(self) -> None:
        response = build_health_response(os.environ)
        if response.failure_code:
            # Only a fixed category is logged; provider exceptions and DSNs are
            # deliberately discarded by the probe boundary.
            print(
                f"competition_health_failed category={response.failure_code}",
                file=sys.stderr,
            )
        body = json.dumps(
            response.payload,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(response.http_status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        # Vercel already records request metadata. Avoid duplicating raw paths.
        return
