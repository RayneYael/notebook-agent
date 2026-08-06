from __future__ import annotations

import hashlib
import ast
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import zipfile

import pytest


ROOT = Path(__file__).parents[1]
PATCH = ROOT / "integrations/langbot-4.10.6-redact-monitoring.patch"
PINNED_LANGBOT_SHA256 = "ee950fd6a687cb8c7cfe646d2b9a92cfbf09b3ddfbaf8f43ea0613905d3ffbff"


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
        "langbot/pkg/plugin/connector.py",
        "langbot/pkg/pipeline/pipelinemgr.py",
        "langbot/pkg/platform/botmgr.py",
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
