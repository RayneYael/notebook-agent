"""Export the complete browser contract without touching DB, queues, or secrets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.api.app import WebApiServices, create_app


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web" / "src" / "api" / "openapi.json"


def rendered_schema() -> str:
    placeholder = object()
    app = create_app(
        services=WebApiServices(
            web_auth=placeholder,
            library=placeholder,
            submission=placeholder,
            transcript=placeholder,
        ),
        expected_origin="https://contract.invalid",
        cookie_secure=True,
        publish_budget_seconds=1.0,
    )
    return json.dumps(
        app.openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_schema()
    if args.check:
        actual = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if actual != expected:
            raise SystemExit("web/src/api/openapi.json is stale; regenerate it")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
