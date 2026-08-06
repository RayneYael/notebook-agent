"""Operator and local Agent command-line entry points."""

import argparse
import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.bootstrap import build_channel_service, build_embedding_provider
from app.channels.http_gateway import serve as serve_channel_gateway
from app.channels.types import ChannelEnvelope
from app.config import get_settings
from app.db import get_session_factory, session
from app.ingest.tasks import ingest_url
from app.models import AppUser, ChannelIdentity
from app.retrieval.search import bm25_search, vector_search


def _print(name, hits):
    print(f"\n{name}")
    for rank, hit in enumerate(hits, 1):
        print(f"{rank:>2}. {hit.title or hit.platform_id} | {hit.url} | {hit.score:.4f}\n    {hit.text[:240]}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="kb")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("url")
    ingest.add_argument("--user-id", type=int, required=True)
    ingest.add_argument("--why-saved")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--user-id", type=int, required=True)
    search.add_argument("-k", type=int, default=10)
    ask = commands.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--user-id", type=int, required=True)
    ask.add_argument("--thread", default="default")
    users = commands.add_parser("users")
    user_commands = users.add_subparsers(dest="user_command", required=True)
    user_commands.add_parser("create")
    for command in ("show", "disable", "enable"):
        child = user_commands.add_parser(command)
        child.add_argument("--user-id", type=int, required=True)
    rebind = user_commands.add_parser("rebind-identity")
    rebind.add_argument("--identity-id", type=int, required=True)
    rebind.add_argument("--user-id", type=int, required=True)
    commands.add_parser("gateway-server")
    args = parser.parse_args()
    if args.command == "users":
        _users(args)
        return
    if args.command == "ingest":
        item_id, state = ingest_url(
            args.url, user_id=args.user_id, why_saved=args.why_saved
        )
        print(f"item={item_id} state={state}")
        return
    settings = get_settings()
    if args.command == "gateway-server":
        serve_channel_gateway(settings)
        return
    if args.command == "ask":
        asyncio.run(_ask(args, settings))
        return
    embedder = build_embedding_provider(settings)
    if embedder is None:
        raise SystemExit("embedding provider is not configured")
    with session() as db:
        lexical = bm25_search(db, args.query, user_id=args.user_id, k=args.k)
        vector = vector_search(
            db, embedder.embed([args.query])[0], user_id=args.user_id, k=args.k
        )
    _print("BM25 / trigram", lexical)
    _print("Vector", vector)


def _users(args) -> None:
    factory = get_session_factory()
    with factory() as db:
        if args.user_command == "create":
            user = AppUser()
            db.add(user)
            db.commit()
            print(f"user={user.id}")
            return
        if args.user_command == "rebind-identity":
            user = db.get(AppUser, args.user_id)
            identity = db.get(ChannelIdentity, args.identity_id)
            if user is None:
                raise SystemExit(f"app user {args.user_id} not found")
            if identity is None:
                raise SystemExit(f"channel identity {args.identity_id} not found")
            identity.app_user_id = user.id
            db.commit()
            print(f"identity={identity.id} user={user.id}")
            return
        user = db.get(AppUser, args.user_id)
        if user is None:
            raise SystemExit(f"app user {args.user_id} not found")
        if args.user_command == "disable":
            user.disabled_at = datetime.now(UTC)
            db.commit()
        elif args.user_command == "enable":
            user.disabled_at = None
            db.commit()
        state = "disabled" if user.disabled_at else "active"
        print(f"user={user.id} state={state}")


async def _ask(args, settings) -> None:
    factory = get_session_factory()
    _ensure_cli_identity(factory, args.user_id)
    service = build_channel_service(settings)
    envelope = ChannelEnvelope(
        channel="cli",
        account_id="local",
        external_user_id=str(args.user_id),
        conversation_id=args.thread,
        message_id=str(uuid.uuid4()),
        text=args.question,
    )
    answer = await service.handle(envelope)
    print(answer.text)
    if answer.status == "failed":
        raise SystemExit(2)


def _ensure_cli_identity(factory, user_id: int) -> None:
    with factory() as db:
        user = db.get(AppUser, user_id)
        if user is None:
            raise SystemExit(f"app user {user_id} not found")
        if user.disabled_at is not None:
            raise SystemExit(f"app user {user_id} is disabled")
        identity = db.scalar(
            select(ChannelIdentity).where(
                ChannelIdentity.channel == "cli",
                ChannelIdentity.account_id == "local",
                ChannelIdentity.external_user_id == str(user_id),
            )
        )
        if identity is None:
            db.add(
                ChannelIdentity(
                    app_user_id=user_id,
                    channel="cli",
                    account_id="local",
                    external_user_id=str(user_id),
                )
            )
            db.commit()
        elif identity.app_user_id != user_id:
            raise SystemExit("CLI identity is already bound to another user")


if __name__ == "__main__":
    main()
