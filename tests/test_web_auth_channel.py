from contextlib import AbstractContextManager

import pytest

from app.agent.types import AgentAnswer
from app.channels.service import ChannelService, _command
from app.channels.types import ChannelEnvelope, TenantContext
from app.config import Settings


class _Session(AbstractContextManager):
    def commit(self):
        return None

    def __exit__(self, *args):
        return None


class _AgentMustNotRun:
    async def run(self, *args, **kwargs):
        raise AssertionError("Agent must not run for /web-login")


class _AuthRecorder:
    def __init__(self):
        self.calls = []

    def approve(self, code, tenant):
        self.calls.append((code, tenant))


def _envelope(text="/web-login ABCD-EFGH"):
    return ChannelEnvelope(
        "telegram", "bot", "external", "chat", "message", text
    )


def _settings():
    return Settings(
        database_url="postgresql+psycopg://unused/unused",
        redis_url="redis://unused/0",
    )


def test_web_login_command_is_parsed_deterministically():
    assert _command("/web-login ABCD-EFGH") == (
        "web-login",
        "ABCD-EFGH",
    )
    assert _command("/web-login@knowledge_bot ABCD-EFGH") == (
        "web-login",
        "ABCD-EFGH",
    )


@pytest.mark.asyncio
async def test_web_login_resolves_trusted_identity_approves_and_skips_agent(
    monkeypatch,
):
    tenant = TenantContext(7, 11, "telegram", "bot", "external")
    monkeypatch.setattr(
        "app.channels.service.resolve_or_register",
        lambda db, envelope: tenant,
    )
    auth = _AuthRecorder()
    service = ChannelService(
        _Session,
        _AgentMustNotRun(),
        _settings(),
        web_auth=auth,
    )

    answer = await service.handle(_envelope())

    assert auth.calls == [("ABCD-EFGH", tenant)]
    assert answer == AgentAnswer(
        status="ok",
        text="网页登录已批准，请返回浏览器继续。",
    )


@pytest.mark.asyncio
async def test_web_login_without_code_or_service_returns_safe_error(monkeypatch):
    monkeypatch.setattr(
        "app.channels.service.resolve_or_register",
        lambda db, envelope: TenantContext(7, 11, "telegram", "bot", "external"),
    )
    service = ChannelService(_Session, _AgentMustNotRun(), _settings())

    missing_code = await service.handle(_envelope("/web-login"))
    unavailable = await service.handle(_envelope())

    assert missing_code.error_code == "web_login_usage"
    assert unavailable.error_code == "web_login_unavailable"
    assert "ABCD-EFGH" not in unavailable.text
