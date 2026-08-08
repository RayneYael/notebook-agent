from types import SimpleNamespace

import uvicorn

from app import cli
from app.api import runtime


def test_web_server_disables_query_bearing_uvicorn_access_logs(monkeypatch):
    settings = SimpleNamespace(
        web_host="127.0.0.1",
        web_port=8000,
        web_forwarded_allow_ips="127.0.0.1",
    )
    application = object()
    captured = {}
    monkeypatch.setattr("sys.argv", ["kb", "web-server"])
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime, "build_web_app", lambda value: application)
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, **kwargs),
    )

    cli.main()

    assert captured["app"] is application
    assert captured["access_log"] is False
