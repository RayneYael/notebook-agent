import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.deployment_health import build_health_response, probe_database


POOLED_URL = (
    "postgresql://notebook:secret-value@"
    "ep-example-pooler.us-east-2.aws.neon.tech/notebook"
    "?sslmode=require"
)
REVISION = "c7e8a91b2d34"


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.executed.append((statement, parameters))

    def fetchone(self):
        return self.rows.pop(0)


class FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.cursor_instance


def connector_with(rows, calls):
    def connect(database_url, **kwargs):
        calls.append((database_url, kwargs))
        return FakeConnection(rows)

    return connect


def test_ready_response_checks_database_and_schema():
    calls = []
    response = build_health_response(
        {
            "DATABASE_URL": POOLED_URL,
            "EXPECTED_DATABASE_REVISION": REVISION,
            "DEPLOYMENT_ENV": "competition",
        },
        connect=connector_with([(1,), (REVISION,)], calls),
    )

    assert response.http_status == 200
    assert response.failure_code is None
    assert response.payload == {
        "status": "ok",
        "environment": "competition",
        "database": {"status": "ok", "revision": REVISION},
    }
    assert calls == [(POOLED_URL, {"connect_timeout": 5})]


def test_runtime_rejects_direct_or_non_tls_database_urls_before_connecting():
    calls = []
    direct_url = POOLED_URL.replace("-pooler", "")

    direct = probe_database(
        direct_url,
        REVISION,
        connect=connector_with([(1,), (REVISION,)], calls),
    )
    non_tls = probe_database(
        POOLED_URL.replace("sslmode=require", "sslmode=disable"),
        REVISION,
        connect=connector_with([(1,), (REVISION,)], calls),
    )

    assert not direct.ready
    assert direct.failure_code == "database_url_invalid"
    assert not non_tls.ready
    assert non_tls.failure_code == "database_url_invalid"
    assert calls == []


def test_missing_configuration_is_redacted_and_unavailable():
    response = build_health_response({})

    assert response.http_status == 503
    assert response.failure_code == "database_url_missing"
    assert response.payload == {
        "status": "unavailable",
        "environment": "competition",
        "database": {"status": "unavailable"},
    }


def test_provider_failure_does_not_leak_exception_or_database_url():
    def failed_connect(database_url, **kwargs):
        raise RuntimeError(f"could not connect using {database_url}")

    response = build_health_response(
        {
            "DATABASE_URL": POOLED_URL,
            "EXPECTED_DATABASE_REVISION": REVISION,
        },
        connect=failed_connect,
    )
    rendered = json.dumps(response.payload)

    assert response.http_status == 503
    assert response.failure_code == "database_unavailable"
    assert "secret-value" not in rendered
    assert "neon.tech" not in rendered
    assert "could not connect" not in rendered


def test_schema_mismatch_fails_closed_without_returning_actual_revision():
    response = build_health_response(
        {
            "DATABASE_URL": POOLED_URL,
            "EXPECTED_DATABASE_REVISION": REVISION,
        },
        connect=connector_with([(1,), ("older-revision",)], []),
    )

    assert response.http_status == 503
    assert response.failure_code == "database_schema_mismatch"
    assert "older-revision" not in json.dumps(response.payload)


def test_vercel_config_allowlists_health_routes_and_excludes_local_secrets():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "vercel.json").read_text())

    alembic_config = Config(str(root / "alembic.ini"))
    migration_head = ScriptDirectory.from_config(alembic_config).get_current_head()
    assert config["env"]["EXPECTED_DATABASE_REVISION"] == migration_head
    assert config["outputDirectory"] == "public"
    assert (root / "public" / ".gitkeep").is_file()

    assert config["routes"] == [
        {"src": "^/$", "dest": "/api/health"},
        {"src": "^/health$", "dest": "/api/health"},
        {"src": "^/api/health$", "dest": "/api/health"},
        {"src": "^/.*$", "status": 404},
    ]
    excluded = config["functions"]["api/health.py"]["excludeFiles"]
    assert ".env.*" in excluded
    assert ".vercel/**" in excluded
