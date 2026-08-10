"""Email proof and hash-only browser sessions for the same-origin Web API.

This module owns normalization and all secret transformations.  Route handlers
receive only stable error codes and never persist or log raw codes/tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import smtplib
import ssl
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.channels.identity import ensure_explicit_identity
from app.channels.types import TenantContext
from app.config import Settings
from app.db import get_session_factory
from app.models import AppUser, ChannelIdentity, WebAuthChallenge, WebSession


WEB_CHANNEL = "web"
WEB_ACCOUNT_ID = "web"
_EMAIL_RE = re.compile(r"(?=.{3,254}\Z)[^\s@]+@[^\s@]+\.[^\s@]+\Z")


class WebAuthError(ValueError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class InvalidEmail(WebAuthError):
    def __init__(self) -> None:
        super().__init__("invalid_email")


class InvalidVerification(WebAuthError):
    def __init__(self) -> None:
        super().__init__("invalid_verification")


class EmailDeliveryUnavailable(WebAuthError):
    def __init__(self) -> None:
        super().__init__("email_delivery_unavailable")


class LoginRateLimited(WebAuthError):
    def __init__(self) -> None:
        super().__init__("login_rate_limited")


class InvalidSession(WebAuthError):
    def __init__(self) -> None:
        super().__init__("invalid_session")


class EmailSender(Protocol):
    def send_login_code(self, to_email: str, code: str, expires_at: datetime) -> None: ...


class LoginRateLimiter(Protocol):
    def allow(self, email: str, client_ip: str, *, now: datetime) -> bool: ...


@dataclass(frozen=True)
class SentEmail:
    to_email: str
    code: str
    expires_at: datetime


class InMemoryEmailSender:
    """Test/development sender; values remain in-process and are never logged."""

    def __init__(self) -> None:
        self.messages: list[SentEmail] = []

    @property
    def sent(self) -> list[SentEmail]:
        """Compatibility alias for tests without exposing a production sink."""
        return self.messages

    def send_login_code(self, to_email: str, code: str, expires_at: datetime) -> None:
        self.messages.append(SentEmail(to_email, code, expires_at))


class ResendEmailSender:
    """Small Resend adapter which intentionally discards provider response bodies."""

    endpoint = "https://api.resend.com/emails"

    def __init__(self, api_key: str, from_email: str, *, timeout_seconds: float = 10.0, client=None) -> None:
        if not api_key or not from_email or timeout_seconds <= 0:
            raise ValueError("Resend sender requires credentials and a positive timeout")
        self._api_key = api_key
        self._from_email = from_email
        self._timeout = timeout_seconds
        self._client = client

    def send_login_code(self, to_email: str, code: str, expires_at: datetime) -> None:
        payload = {
            "from": self._from_email,
            "to": [to_email],
            "subject": "Your Notebook Agent login code",
            "text": f"Your login code is {code}. It expires at {expires_at.isoformat()}.",
        }
        try:
            if self._client is not None:
                response = self._client.post(
                    self.endpoint, headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload, timeout=self._timeout,
                )
            else:
                with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
                    response = client.post(
                        self.endpoint, headers={"Authorization": f"Bearer {self._api_key}"}, json=payload
                    )
            if response.status_code < 200 or response.status_code >= 300:
                raise EmailDeliveryUnavailable()
        except EmailDeliveryUnavailable:
            raise
        except Exception:
            # Never include response text, request data, API credentials, or code.
            raise EmailDeliveryUnavailable() from None


class SmtpEmailSender:
    """SMTP submission adapter with an explicit STARTTLS authentication flow."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        *,
        starttls: bool = True,
        timeout_seconds: float = 10.0,
        client_factory=None,
    ) -> None:
        if (
            not all((host, username, password, from_email))
            or not 1 <= port <= 65535
            or timeout_seconds <= 0
        ):
            raise ValueError("SMTP sender requires complete credentials and a valid timeout")
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._starttls = starttls
        self._timeout = timeout_seconds
        self._client_factory = client_factory or smtplib.SMTP

    def send_login_code(self, to_email: str, code: str, expires_at: datetime) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to_email
        message["Subject"] = "Your Notebook Agent login code"
        message.set_content(
            f"Your login code is {code}. It expires at {expires_at.isoformat()}."
        )
        client = None
        try:
            client = self._client_factory(self._host, self._port, timeout=self._timeout)
            client.ehlo()
            if self._starttls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(self._username, self._password)
            client.send_message(message)
        except Exception:
            # Never preserve SMTP responses, provider errors, credentials, or code.
            raise EmailDeliveryUnavailable() from None
        finally:
            if client is not None:
                try:
                    client.quit()
                except Exception:
                    pass


class InMemoryLoginRateLimiter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._secret = (settings.web_auth_secret or "").encode()
        self._email_sends: dict[str, deque[datetime]] = defaultdict(deque)
        self._ip_sends: dict[str, deque[datetime]] = defaultdict(deque)
        self._last_email_send: dict[str, datetime] = {}

    def allow(self, email: str, client_ip: str, *, now: datetime) -> bool:
        # Keep fake state shaped like production: neither an email nor an IP
        # becomes a dictionary/Redis key in clear text.
        email_key = hmac.new(self._secret, email.encode(), hashlib.sha256).hexdigest()
        ip_key = hmac.new(self._secret, client_ip.encode(), hashlib.sha256).hexdigest()
        email_queue = self._email_sends[email_key]
        ip_queue = self._ip_sends[ip_key]
        _trim(email_queue, now - timedelta(seconds=self._settings.web_auth_email_window_seconds))
        _trim(ip_queue, now - timedelta(seconds=self._settings.web_auth_ip_window_seconds))
        previous = self._last_email_send.get(email_key)
        if previous and now - previous < timedelta(seconds=self._settings.web_auth_resend_seconds):
            return False
        if len(email_queue) >= self._settings.web_auth_email_max_sends or len(ip_queue) >= self._settings.web_auth_ip_max_sends:
            return False
        email_queue.append(now)
        ip_queue.append(now)
        self._last_email_send[email_key] = now
        return True


class RedisLoginRateLimiter:
    """Redis limiter with HMAC-obscured keys and fail-closed operation."""

    _SCRIPT = """
local now = tonumber(ARGV[1]); local resend = tonumber(ARGV[2]);
local email_window = tonumber(ARGV[3]); local email_max = tonumber(ARGV[4]);
local ip_window = tonumber(ARGV[5]); local ip_max = tonumber(ARGV[6]);
local last = tonumber(redis.call('GET', KEYS[1]) or '0');
if last > 0 and now - last < resend then return 0 end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - email_window);
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now - ip_window);
if redis.call('ZCARD', KEYS[2]) >= email_max or redis.call('ZCARD', KEYS[3]) >= ip_max then return 0 end
local member = tostring(now) .. ':' .. tostring(math.random());
redis.call('SET', KEYS[1], now, 'EX', resend);
redis.call('ZADD', KEYS[2], now, member); redis.call('EXPIRE', KEYS[2], email_window);
redis.call('ZADD', KEYS[3], now, member); redis.call('EXPIRE', KEYS[3], ip_window);
return 1
"""

    def __init__(self, redis_client, settings: Settings) -> None:
        self._redis = redis_client
        self._settings = settings
        self._secret = (settings.web_auth_secret or "").encode()

    def _key(self, value: str) -> str:
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()

    def allow(self, email: str, client_ip: str, *, now: datetime) -> bool:
        try:
            email_key, ip_key = self._key(email), self._key(client_ip)
            result = self._redis.eval(
                self._SCRIPT, 3, f"web-auth:last:{email_key}", f"web-auth:email:{email_key}", f"web-auth:ip:{ip_key}",
                int(now.timestamp()), self._settings.web_auth_resend_seconds,
                self._settings.web_auth_email_window_seconds, self._settings.web_auth_email_max_sends,
                self._settings.web_auth_ip_window_seconds, self._settings.web_auth_ip_max_sends,
            )
            return int(result) == 1
        except Exception:
            return False


@dataclass(frozen=True)
class AuthenticatedWebSession:
    session_id: int
    tenant: TenantContext
    expires_at: datetime
    public_id: str


@dataclass(frozen=True)
class VerifiedWebLogin:
    raw_session_token: str
    raw_csrf_token: str
    session: AuthenticatedWebSession


class WebAuthService:
    def __init__(self, session_factory: Callable[[], Session], settings: Settings, sender: EmailSender, limiter: LoginRateLimiter) -> None:
        self._session_factory, self._settings = session_factory, settings
        self._sender, self._limiter = sender, limiter
        if not settings.web_auth_secret:
            raise ValueError("WEB_AUTH_SECRET is required for Web authentication")
        self._secret = settings.web_auth_secret.encode()

    def request_challenge(self, email: str, client_ip: str, *, now: datetime | None = None) -> None:
        canonical = canonical_email(email)
        current = _utc(now)
        if not self._limiter.allow(canonical, client_ip, now=current):
            raise LoginRateLimited()
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self._session_factory() as db:
            db.execute(update(WebAuthChallenge).where(
                WebAuthChallenge.email == canonical,
                WebAuthChallenge.consumed_at.is_(None), WebAuthChallenge.invalidated_at.is_(None),
            ).values(invalidated_at=current))
            challenge = WebAuthChallenge(email=canonical, code_hash="", expires_at=current + timedelta(seconds=self._settings.web_auth_code_ttl_seconds), sent_at=current)
            _sqlite_id(db, challenge, WebAuthChallenge)
            db.add(challenge)
            db.flush()
            challenge.code_hash = self._code_hash(challenge.id, code)
            try:
                self._sender.send_login_code(canonical, code, challenge.expires_at)
            except EmailDeliveryUnavailable:
                challenge.delivery_failed_at = current
                db.commit()
                raise
            db.commit()

    def verify(self, email: str, code: str, *, now: datetime | None = None) -> VerifiedWebLogin:
        canonical = canonical_email(email)
        if not re.fullmatch(r"\d{6}", str(code)):
            raise InvalidVerification()
        current = _utc(now)
        with self._session_factory() as db:
            challenge = db.scalar(select(WebAuthChallenge).where(
                WebAuthChallenge.email == canonical,
            ).order_by(WebAuthChallenge.created_at.desc(), WebAuthChallenge.id.desc()).with_for_update())
            if challenge is None or challenge.consumed_at or challenge.invalidated_at or challenge.delivery_failed_at or _utc(challenge.expires_at) <= current or challenge.attempt_count >= self._settings.web_auth_max_attempts:
                raise InvalidVerification()
            challenge.attempt_count += 1
            if not hmac.compare_digest(challenge.code_hash, self._code_hash(challenge.id, str(code))):
                db.commit()
                raise InvalidVerification()
            challenge.consumed_at = current
            identity = db.scalar(select(ChannelIdentity).where(
                ChannelIdentity.channel == WEB_CHANNEL, ChannelIdentity.account_id == WEB_ACCOUNT_ID,
                ChannelIdentity.external_user_id == canonical,
            ).with_for_update())
            if identity is None:
                user = AppUser()
                _sqlite_id(db, user, AppUser)
                db.add(user)
                db.flush()
                tenant = ensure_explicit_identity(db, app_user_id=user.id, channel=WEB_CHANNEL, account_id=WEB_ACCOUNT_ID, external_user_id=canonical)
            else:
                tenant = TenantContext(identity.app_user_id, identity.id, identity.channel, identity.account_id, identity.external_user_id)
                user = db.get(AppUser, identity.app_user_id)
                if user is None or user.disabled_at is not None or identity.disabled_at is not None:
                    raise InvalidVerification()
            raw = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            session = WebSession(
                public_id=secrets.token_urlsafe(24),
                app_user_id=tenant.app_user_id,
                channel_identity_id=tenant.channel_identity_id,
                token_hash=_token_hash(raw),
                csrf_token_hash=_token_hash(csrf),
                login_channel=WEB_CHANNEL,
                expires_at=(
                    current
                    + timedelta(seconds=self._settings.web_session_ttl_seconds)
                ),
            )
            _sqlite_id(db, session, WebSession)
            db.add(session)
            db.commit()
            return VerifiedWebLogin(
                raw,
                csrf,
                AuthenticatedWebSession(
                    session.id, tenant, session.expires_at, session.public_id
                ),
            )

    def resolve_session(self, raw_token: str, *, now: datetime | None = None) -> AuthenticatedWebSession:
        try:
            digest = _token_hash(raw_token)
        except ValueError:
            raise InvalidSession() from None
        current = _utc(now)
        with self._session_factory() as db:
            session = db.scalar(select(WebSession).where(WebSession.token_hash == digest))
            if session is None or not hmac.compare_digest(session.token_hash, digest) or session.revoked_at is not None or _utc(session.expires_at) <= current:
                raise InvalidSession()
            if session.channel_identity_id is None:
                raise InvalidSession()
            user = db.get(AppUser, session.app_user_id)
            identity = db.get(ChannelIdentity, session.channel_identity_id)
            if user is None or identity is None or user.disabled_at is not None or identity.disabled_at is not None or identity.app_user_id != user.id or identity.channel != WEB_CHANNEL:
                raise InvalidSession()
            session.last_used_at = current
            db.commit()
            return AuthenticatedWebSession(
                session.id,
                TenantContext(
                    user.id,
                    identity.id,
                    identity.channel,
                    identity.account_id,
                    identity.external_user_id,
                ),
                session.expires_at,
                session.public_id,
            )

    def validate_csrf(
        self, raw_token: str, raw_csrf_token: str, *, now: datetime | None = None
    ) -> None:
        try:
            token_hash = _token_hash(raw_token)
            csrf_hash = _token_hash(raw_csrf_token)
        except ValueError:
            raise InvalidSession() from None
        current = _utc(now)
        with self._session_factory() as db:
            session = db.scalar(
                select(WebSession).where(WebSession.token_hash == token_hash)
            )
            if (
                session is None
                or session.revoked_at is not None
                or _utc(session.expires_at) <= current
                or not hmac.compare_digest(session.csrf_token_hash, csrf_hash)
            ):
                raise InvalidSession()

    def revoke_session(self, raw_token: str, *, now: datetime | None = None) -> None:
        digest = _token_hash(raw_token)
        with self._session_factory() as db:
            session = db.scalar(select(WebSession).where(WebSession.token_hash == digest).with_for_update())
            if session is not None:
                session.revoked_at = session.revoked_at or _utc(now)
                db.commit()

    @staticmethod
    def revoke_user_sessions(db: Session, app_user_id: int, *, now: datetime | None = None) -> None:
        db.execute(update(WebSession).where(WebSession.app_user_id == app_user_id, WebSession.revoked_at.is_(None)).values(revoked_at=_utc(now)))

    def _code_hash(self, challenge_id: int, code: str) -> str:
        return hmac.new(self._secret, f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def canonical_email(value: str) -> str:
    email = str(value).strip().casefold()
    if not _EMAIL_RE.fullmatch(email):
        raise InvalidEmail()
    return email


def _token_hash(raw: str) -> str:
    token = str(raw).strip()
    if not token or len(token) > 512:
        raise ValueError("invalid session token")
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _trim(values: deque[datetime], cutoff: datetime) -> None:
    while values and values[0] <= cutoff:
        values.popleft()


def _sqlite_id(db: Session, record, model) -> None:
    if getattr(getattr(db, "bind", None), "dialect", None) is not None and db.bind.dialect.name == "sqlite":
        record.id = int(db.scalar(select(func.max(model.id))) or 0) + 1


def revoke_web_sessions(db: Session, app_user_id: int, *, now: datetime | None = None) -> None:
    """Transaction-scoped helper used by every account-disable path."""

    WebAuthService.revoke_user_sessions(db, app_user_id, now=now)


def build_email_auth_service(
    settings: Settings, session_factory=None
) -> WebAuthService:
    """Build the one email-login service shared by HTTP entry points."""

    factory = session_factory or get_session_factory()
    provider = (settings.email_provider or "").strip().lower()
    if provider == "resend":
        sender: EmailSender = ResendEmailSender(
            settings.resend_api_key or "",
            settings.resend_from_email or "",
            timeout_seconds=settings.resend_timeout_seconds,
        )
    elif provider == "smtp":
        sender = SmtpEmailSender(
            settings.smtp_host or "",
            settings.smtp_port,
            settings.smtp_username or "",
            settings.smtp_password or "",
            settings.smtp_from_email or "",
            starttls=settings.smtp_starttls,
            timeout_seconds=settings.smtp_timeout_seconds,
        )
    elif settings.notebook_agent_env == "production":
        raise RuntimeError("Web authentication email sender is unavailable")
    else:
        sender = InMemoryEmailSender()
    if settings.notebook_agent_env == "production":
        try:
            import redis

            limiter: LoginRateLimiter = RedisLoginRateLimiter(
                redis.Redis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                ),
                settings,
            )
        except Exception:
            class _ClosedLimiter:
                def allow(
                    self, email: str, client_ip: str, *, now: datetime
                ) -> bool:
                    return False

            limiter = _ClosedLimiter()
    else:
        limiter = InMemoryLoginRateLimiter(settings)
    return WebAuthService(factory, settings, sender, limiter)
