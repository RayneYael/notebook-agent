from __future__ import annotations

import asyncio
import hashlib
import ast
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import time
import types
from dataclasses import dataclass
from typing import Any
import zipfile

import certifi
import pytest


ROOT = Path(__file__).parents[1]
PATCH = ROOT / "integrations/langbot-4.10.6-redact-monitoring.patch"
PINNED_LANGBOT_SHA256 = "ee950fd6a687cb8c7cfe646d2b9a92cfbf09b3ddfbaf8f43ea0613905d3ffbff"


class _AiohttpForPatchTests:
    class ClientConnectorCertificateError(Exception):
        pass


@pytest.fixture(scope="module")
def applied_langbot_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Apply the versioned patch to an offline 4.10.6 source baseline."""
    source_root = tmp_path_factory.mktemp("langbot-openclaw-source") / "source"
    wheel_path_value = os.environ.get("LANGBOT_4_10_6_WHEEL")
    if wheel_path_value:
        wheel_path = Path(wheel_path_value)
        assert wheel_path.is_file()
        assert hashlib.sha256(wheel_path.read_bytes()).hexdigest() == PINNED_LANGBOT_SHA256
        with zipfile.ZipFile(wheel_path) as wheel:
            wheel.extractall(source_root)
    else:
        local_baseline = ROOT / ".runtime/langbot/patched_site.pre-readiness-20260806/langbot"
        if not local_baseline.is_dir():
            pytest.skip("set LANGBOT_4_10_6_WHEEL or provide the local 4.10.6 baseline")
        shutil.copytree(local_baseline, source_root / "langbot")

    dry_run = subprocess.run(
        ["patch", "--batch", "--dry-run", "-p1", "-i", str(PATCH)],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    applied = subprocess.run(
        ["patch", "--batch", "-p1", "-i", str(PATCH)],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    return source_root


def _patched_definitions(
    path: Path,
    names: set[str],
    namespace: dict[str, Any],
    *,
    class_name: str | None = None,
) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    candidates: list[ast.stmt] = tree.body
    if class_name:
        candidates = next(
            node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
        )
    selected = [node for node in candidates if getattr(node, "name", None) in names]
    future = ast.parse("from __future__ import annotations").body[0]
    exec(compile(ast.Module(body=[future, *selected], type_ignores=[]), str(path), "exec"), namespace)
    return {name: namespace[name] for name in names}


class _AdapterLogger:
    def __init__(self) -> None:
        self.entries: list[str] = []

    async def info(self, message: str) -> None:
        self.entries.append(message)

    async def warning(self, message: str) -> None:
        self.entries.append(message)

    async def error(self, message: str) -> None:
        self.entries.append(message)


def _adapter_methods(applied_langbot_source: Path) -> dict[str, Any]:
    client_path = applied_langbot_source / "langbot/libs/openclaw_weixin_api/client.py"
    client_namespace: dict[str, Any] = {
        "aiohttp": _AiohttpForPatchTests,
        "dataclass": dataclass,
        "os": os,
        "Path": Path,
        "ssl": ssl,
    }
    client = _patched_definitions(
        client_path,
        {
            "TLSConfigurationError",
            "TrustedCA",
            "_readable_bundle",
            "configure_explicit_trusted_ca",
            "is_certificate_verification_error",
        },
        client_namespace,
    )
    adapter_namespace: dict[str, Any] = {
        "asyncio": asyncio,
        "DEFAULT_BASE_URL": "https://ilinkai.weixin.qq.com",
        "SESSION_EXPIRED_ERRCODE": -14,
        "time": time,
        "typing": __import__("typing"),
        "TLSConfigurationError": client["TLSConfigurationError"],
        "configure_explicit_trusted_ca": client["configure_explicit_trusted_ca"],
        "is_certificate_verification_error": client["is_certificate_verification_error"],
    }
    adapter = _patched_definitions(
        applied_langbot_source / "langbot/pkg/platform/sources/openclaw_weixin.py",
        {
            "get_readiness",
            "_mark_healthy",
            "_mark_retrying",
            "_mark_failed",
            "_configure_explicit_tls",
            "_poll_loop",
            "run_async",
        },
        adapter_namespace,
        class_name="OpenClawWeixinAdapter",
    )
    return {**client, **adapter}


def _fake_adapter(methods: dict[str, Any], client: Any) -> types.SimpleNamespace:
    adapter = types.SimpleNamespace(
        name="openclaw-weixin",
        config={"poll_timeout": 1},
        client=client,
        logger=_AdapterLogger(),
        _trusted_ca=None,
        _readiness_state="starting",
        _last_error_code=None,
        _last_error_class=None,
        _last_success_monotonic=None,
        _retry_count=0,
        _next_retry_monotonic=None,
        _polling=True,
        _poll_task=None,
        bot_account_id="",
    )
    for name in (
        "get_readiness",
        "_mark_healthy",
        "_mark_retrying",
        "_mark_failed",
        "_configure_explicit_tls",
        "_poll_loop",
        "run_async",
    ):
        setattr(adapter, name, types.MethodType(methods[name], adapter))
    return adapter


def test_startup_patch_contains_readiness_and_fail_closed_contract() -> None:
    patch_text = PATCH.read_text(encoding="utf-8")

    # Startup is state-driven: the adapter gate waits for a live runtime and
    # the runtime-reported initialized state, rather than a guessed delay.
    assert "required_plugins: []" in patch_text
    assert "required_plugins_ready_timeout_seconds: 30" in patch_text
    assert "asyncio.wait_for(self._runtime_connected.wait(), timeout=remaining)" in patch_text
    assert "status.get('status') == 'initialized'" in patch_text
    assert "timed out waiting for required plugins to initialize" in patch_text

    # A bridge pipeline validates event ownership before it can reach the
    # default processor. Non-required pipelines retain upstream behavior.
    assert "required_plugins_for_pipeline(bound_plugins)" in patch_text
    assert "validate_required_plugin_event(event_ctx, bound_plugins)" in patch_text
    assert "await self._reply_fail_closed(query, plugin_error)" in patch_text
    assert "await self._execute_from_stage(0, query)" not in patch_text
    assert "component_manifest.get('manifest', component_manifest)" in patch_text
    assert "_emitted_plugin_ref(plugin)" in patch_text

    # The patch must remove every known private-message log/storage path.
    assert "Private message received [redacted]" in patch_text
    assert "message content redacted" in patch_text
    assert "'message_preview': str(message_chain)[:200]" in patch_text
    assert "user_id='redacted'" in patch_text


def test_openclaw_tls_and_poll_readiness_contract_is_versioned() -> None:
    patch_text = PATCH.read_text(encoding="utf-8")

    # An explicit OpenClaw CA override remains verified and is client-local.
    # Without one, the upstream aiohttp/Python verified default is untouched.
    assert "--- a/langbot/libs/openclaw_weixin_api/client.py" in patch_text
    assert "('TLS_CA_BUNDLE', os.environ.get('TLS_CA_BUNDLE'))" in patch_text
    assert "ssl.create_default_context(cafile=bundle_path)" in patch_text
    assert "aiohttp.TCPConnector(ssl=self._ssl_context)" in patch_text
    assert "if self._ssl_context is None:" in patch_text
    assert "self._session = aiohttp.ClientSession()" in patch_text
    assert "configure_explicit_trusted_ca" in patch_text
    assert "async def verify_tls(self) -> None:" not in patch_text
    assert "ssl=False" not in patch_text
    assert "_create_unverified_context" not in patch_text

    # Creating a background poll task is intentionally not a health signal.
    # Only a successful getUpdates response can make this adapter healthy.
    assert "OpenClaw WeChat adapter state=starting; awaiting successful poll" in patch_text
    assert "self._mark_healthy()" in patch_text
    assert "self._mark_failed('certificate_verification_failed', exc)" in patch_text
    assert "self._mark_retrying(exc, backoff_delay)" in patch_text
    assert "'state': self._readiness_state" in patch_text
    assert "'exception_class': self._last_error_class" in patch_text
    assert "'retry_count': self._retry_count" in patch_text

    # Process health remains backwards compatible while the authenticated
    # management surface reports individual adapter readiness.
    assert "def get_adapter_readiness(self) -> list[dict]:" in patch_text
    assert "@self.route('/readiness', methods=['GET'])" in patch_text


def test_send_message_patch_is_redacted_and_keeps_api_key_route(
    applied_langbot_source: Path,
) -> None:
    controller = (
        applied_langbot_source
        / "langbot/pkg/api/http/controller/groups/platform/bots.py"
    ).read_text(encoding="utf-8")

    compile(controller, "bots.py", "exec")
    route_start = controller.index("@self.route('/<bot_uuid>/send_message'")
    route_end = controller.index("# ============ Bot Admins", route_start)
    send_message_route = controller[route_start:route_end]
    assert "auth_type=group.AuthType.API_KEY" in send_message_route
    assert "traceback.print_exc()" not in send_message_route
    assert "str(e)" not in send_message_route
    assert "Failed to send message: " not in send_message_route
    assert "'Failed to send message'" in send_message_route


def test_applied_openclaw_default_tls_is_unchanged_and_explicit_ca_is_verified(
    applied_langbot_source: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    methods = _adapter_methods(applied_langbot_source)
    client_source = (
        applied_langbot_source / "langbot/libs/openclaw_weixin_api/client.py"
    ).read_text(encoding="utf-8")
    adapter_tree = ast.parse(
        (
            applied_langbot_source / "langbot/pkg/platform/sources/openclaw_weixin.py"
        ).read_text(encoding="utf-8")
    )
    configure_method = next(
        node
        for node in ast.walk(adapter_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_configure_explicit_tls"
    )
    assert "import certifi" not in client_source
    assert "os.environ['SSL_CERT_FILE'] =" not in client_source
    assert "os.environ['REQUESTS_CA_BUNDLE'] =" not in client_source
    assert "aiohttp.ClientSession()" in client_source
    assert not any(
        isinstance(node, ast.Attribute) and node.attr in {"_replace_client", "verify_tls"}
        for node in ast.walk(configure_method)
    )

    configure = methods["configure_explicit_trusted_ca"]
    configuration_error = methods["TLSConfigurationError"]
    trusted_bundle = certifi.where()
    environment_bundle = tmp_path / "environment-ca.pem"
    adapter_bundle = tmp_path / "adapter-ca.pem"
    environment_bundle.write_bytes(Path(trusted_bundle).read_bytes())
    adapter_bundle.write_bytes(Path(trusted_bundle).read_bytes())
    invalid_bundle = tmp_path / "invalid.pem"
    invalid_bundle.write_text("not a PEM bundle", encoding="utf-8")

    monkeypatch.delenv("TLS_CA_BUNDLE", raising=False)
    monkeypatch.setenv("SSL_CERT_FILE", "default-ca-sentinel")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "requests-ca-sentinel")
    assert configure() is None
    assert os.environ["SSL_CERT_FILE"] == "default-ca-sentinel"
    assert os.environ["REQUESTS_CA_BUNDLE"] == "requests-ca-sentinel"

    monkeypatch.setenv("TLS_CA_BUNDLE", str(environment_bundle))
    from_environment = configure()
    assert from_environment is not None
    assert from_environment.bundle_path == str(environment_bundle)
    assert from_environment.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert from_environment.ssl_context.check_hostname is True

    from_adapter = configure(str(adapter_bundle))
    assert from_adapter is not None
    assert from_adapter.bundle_path == str(adapter_bundle)
    assert from_adapter.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert from_adapter.ssl_context.check_hostname is True
    assert os.environ["SSL_CERT_FILE"] == "default-ca-sentinel"
    assert os.environ["REQUESTS_CA_BUNDLE"] == "requests-ca-sentinel"

    with pytest.raises(configuration_error):
        configure(str(invalid_bundle))


@pytest.mark.asyncio
async def test_applied_openclaw_invalid_explicit_ca_fails_without_healthy_state(
    applied_langbot_source: Path,
    tmp_path: Path,
) -> None:
    methods = _adapter_methods(applied_langbot_source)

    class Client:
        async def close(self) -> None:
            pass

    invalid_bundle = tmp_path / "invalid.pem"
    invalid_bundle.write_text("not a PEM bundle", encoding="utf-8")
    adapter = _fake_adapter(methods, Client())
    adapter.config["tls_ca_bundle"] = str(invalid_bundle)
    assert await adapter._configure_explicit_tls() is False
    readiness = adapter.get_readiness()
    assert readiness["state"] == "failed"
    assert readiness["error_code"] == "certificate_verification_failed"
    assert readiness["exception_class"] == "TLSConfigurationError"
    assert readiness["last_success_age_seconds"] is None


@pytest.mark.asyncio
async def test_applied_openclaw_poll_state_transitions_are_genuine_and_redacted(
    applied_langbot_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    methods = _adapter_methods(applied_langbot_source)

    class Response:
        longpolling_timeout_ms = None
        ret = 0
        errcode = 0
        get_updates_buf = ""
        msgs: list[Any] = []

    class Client:
        def __init__(self, outcomes: list[Any]) -> None:
            self.outcomes = outcomes
            self.adapter: Any = None

        async def get_updates(self, **_kwargs: Any) -> Response:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            if not self.outcomes:
                self.adapter._polling = False
            return outcome

    async def immediate_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", immediate_sleep)
    transient = Client([asyncio.TimeoutError("private timeout"), Response()])
    adapter = _fake_adapter(methods, transient)
    transient.adapter = adapter
    await adapter._poll_loop()
    readiness = adapter.get_readiness()
    assert readiness["state"] == "healthy"
    assert readiness["error_code"] is None
    assert readiness["retry_count"] == 0
    assert readiness["last_success_age_seconds"] is not None
    assert "private timeout" not in "\n".join(adapter.logger.entries)

    certificate = Client([ssl.SSLCertVerificationError(1, "private certificate")])
    failed_adapter = _fake_adapter(methods, certificate)
    certificate.adapter = failed_adapter
    await failed_adapter._poll_loop()
    failed = failed_adapter.get_readiness()
    assert failed["state"] == "failed"
    assert failed["error_code"] == "certificate_verification_failed"
    assert failed["retry_count"] == 0
    assert "private certificate" not in "\n".join(failed_adapter.logger.entries)


@pytest.mark.asyncio
async def test_applied_openclaw_background_poll_task_is_not_healthy(
    applied_langbot_source: Path,
) -> None:
    methods = _adapter_methods(applied_langbot_source)

    class Client:
        async def close(self) -> None:
            pass

    adapter = _fake_adapter(methods, Client())
    entered_poll = asyncio.Event()

    async def configure_explicit_tls() -> bool:
        return True

    async def replace_client(*, base_url: str, token: str) -> None:
        return None

    async def pending_poll() -> None:
        entered_poll.set()
        await asyncio.Event().wait()

    adapter._configure_explicit_tls = configure_explicit_tls
    adapter._replace_client = replace_client
    adapter._poll_loop = pending_poll
    adapter.config["token"] = "test-token"
    task = asyncio.create_task(adapter.run_async())
    await asyncio.wait_for(entered_poll.wait(), timeout=1)
    assert adapter.get_readiness()["state"] == "starting"
    adapter._poll_task.cancel()
    await asyncio.wait_for(task, timeout=1)


def test_applied_openclaw_removes_qr_identity_and_payload_log_paths(
    applied_langbot_source: Path,
) -> None:
    patched_text = "\n".join(
        (
            (applied_langbot_source / "langbot/libs/openclaw_weixin_api/client.py").read_text(encoding="utf-8"),
            (applied_langbot_source / "langbot/pkg/platform/sources/openclaw_weixin.py").read_text(encoding="utf-8"),
        )
    )
    prohibited = (
        "Please scan the QR code to login WeChat:",
        "WeChat login successful! account_id=",
        "traceback.format_exc()",
        "fetch_qrcode response: qrcode=",
        "QR status poll response: %s",
        "CDN upload: url=%s",
        "logger.error('CDN upload failed: status=%d url=%s body=%s'",
        "return GetUpdatesResponse(ret=0, msgs=[], get_updates_buf=get_updates_buf)",
    )
    for value in prohibited:
        assert value not in patched_text


def test_applied_readiness_route_requires_user_token_by_default(
    applied_langbot_source: Path,
) -> None:
    """Keep readiness protected if either the route or framework default changes."""
    group_tree = ast.parse(
        (applied_langbot_source / "langbot/pkg/api/http/controller/group.py").read_text(encoding="utf-8")
    )
    router_group = next(
        node for node in group_tree.body if isinstance(node, ast.ClassDef) and node.name == "RouterGroup"
    )
    route = next(node for node in router_group.body if isinstance(node, ast.FunctionDef) and node.name == "route")
    route_defaults = dict(zip(route.args.args[-len(route.args.defaults) :], route.args.defaults))
    auth_default = route_defaults[next(arg for arg in route_defaults if arg.arg == "auth_type")]
    assert isinstance(auth_default, ast.Attribute)
    assert isinstance(auth_default.value, ast.Name)
    assert (auth_default.value.id, auth_default.attr) == ("AuthType", "USER_TOKEN")

    adapters_tree = ast.parse(
        (
            applied_langbot_source
            / "langbot/pkg/api/http/controller/groups/platform/adapters.py"
        ).read_text(encoding="utf-8")
    )
    adapters_group = next(
        node for node in adapters_tree.body if isinstance(node, ast.ClassDef) and node.name == "AdaptersRouterGroup"
    )
    readiness_decorator = next(
        decorator
        for node in ast.walk(adapters_group)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
        and decorator.args[0].value == "/readiness"
    )
    assert all(keyword.arg != "auth_type" for keyword in readiness_decorator.keywords)


def test_deployed_connector_accepts_real_nested_plugin_container_dump() -> None:
    """Exercise the helper against the runtime's actual serialized shape."""

    connector_path = ROOT / ".runtime/langbot/patched_site/langbot/pkg/plugin/connector.py"
    if not connector_path.is_file():
        pytest.skip("local patched LangBot runtime is not installed")
    tree = ast.parse(connector_path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_emitted_plugin_ref"
    )
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(connector_path), "exec"), namespace)
    extract = namespace["_emitted_plugin_ref"]

    nested = {
        "manifest": {
            "owner": "notebook-agent",
            "manifest": {
                "metadata": {
                    "author": "notebook-agent",
                    "name": "notebook-knowledge-agent",
                }
            },
        }
    }
    assert extract(nested) == "notebook-agent/notebook-knowledge-agent"
    assert extract({"manifest": {"metadata": {"name": "missing-author"}}}) is None


def test_startup_patch_applies_to_pinned_langbot_wheel_when_supplied(tmp_path: Path) -> None:
    """Validate the real patch against the official pinned wheel when available.

    CI stays network-free: callers that have the wheel set
    ``LANGBOT_4_10_6_WHEEL``. The local deployment verification command sets
    that variable after downloading and verifying the public fixed artifact.
    """

    wheel_path_value = os.environ.get("LANGBOT_4_10_6_WHEEL")
    if not wheel_path_value:
        pytest.skip("set LANGBOT_4_10_6_WHEEL to run fixed-wheel patch verification")

    wheel_path = Path(wheel_path_value)
    assert wheel_path.is_file()
    assert hashlib.sha256(wheel_path.read_bytes()).hexdigest() == PINNED_LANGBOT_SHA256

    source_root = tmp_path / "source"
    with zipfile.ZipFile(wheel_path) as wheel:
        wheel.extractall(source_root)

    command = ["patch", "--batch", "-p1", "-i", str(PATCH)]
    dry_run = subprocess.run(
        ["patch", "--batch", "--dry-run", "-p1", "-i", str(PATCH)],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr

    apply = subprocess.run(
        command,
        cwd=source_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert apply.returncode == 0, apply.stdout + apply.stderr

    changed_files = [
        "langbot/libs/openclaw_weixin_api/client.py",
        "langbot/pkg/plugin/connector.py",
        "langbot/pkg/pipeline/pipelinemgr.py",
        "langbot/pkg/platform/botmgr.py",
        "langbot/pkg/platform/sources/openclaw_weixin.py",
        "langbot/pkg/api/http/controller/groups/platform/adapters.py",
        "langbot/pkg/pipeline/process/process.py",
        "langbot/pkg/pipeline/plugin_diagnostics.py",
        "langbot/pkg/pipeline/monitoring_helper.py",
    ]
    compilation = subprocess.run(
        [sys.executable, "-m", "py_compile", *(str(source_root / path) for path in changed_files)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert compilation.returncode == 0, compilation.stdout + compilation.stderr
