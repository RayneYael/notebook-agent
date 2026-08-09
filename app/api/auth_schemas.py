"""Strict HTTP DTOs for channel-assisted Web authentication."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChallengeCreateRequest(StrictSchema):
    target_channel: Literal["telegram", "wechat"]


class ChallengeCreateResponse(StrictSchema):
    public_id: str
    command: str
    browser_secret: str
    target_channel: Literal["telegram", "wechat"]
    expires_at: datetime


class ChallengeReferenceRequest(StrictSchema):
    public_id: str = Field(min_length=1, max_length=200)


class ChallengeStatusResponse(StrictSchema):
    status: Literal["pending", "approved"]
    expires_at: datetime


class SessionResponse(StrictSchema):
    authenticated: Literal[True] = True
    login_channel: Literal["telegram", "wechat"]
    expires_at: datetime


class AuthErrorResponse(StrictSchema):
    code: str
    message: str
