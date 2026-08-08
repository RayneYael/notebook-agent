from app.models import ContentItem, IngestDispatch, WebLoginChallenge, WebSession


def test_web_auth_models_and_content_public_archive_contract():
    challenge = WebLoginChallenge.__table__
    assert set(challenge.columns) == {
        challenge.c.id,
        challenge.c.public_id,
        challenge.c.code_hash,
        challenge.c.browser_token_hash,
        challenge.c.requester_hash,
        challenge.c.target_channel,
        challenge.c.approved_app_user_id,
        challenge.c.approved_by_identity_id,
        challenge.c.expires_at,
        challenge.c.approved_at,
        challenge.c.consumed_at,
        challenge.c.cancelled_at,
        challenge.c.attempt_count,
        challenge.c.created_at,
    }
    assert challenge.c.public_id.unique
    assert challenge.c.code_hash.unique
    assert "ix_web_login_challenge_created_at" in {
        index.name for index in challenge.indexes
    }

    session = WebSession.__table__
    assert session.c.public_id.unique
    assert session.c.token_hash.unique
    assert not session.c.csrf_token_hash.unique
    assert session.c.app_user_id.foreign_keys
    assert session.c.expires_at.nullable is False
    assert session.c.revoked_at.nullable

    item = ContentItem.__table__
    assert item.c.public_id.unique
    assert item.c.public_id.nullable is False
    assert item.c.archived_at.nullable
    assert "summary" not in item.c
    archive_index = next(
        index
        for index in item.indexes
        if index.name == "ix_content_item_user_archived_saved_at"
    )
    assert [column.name for column in archive_index.columns] == [
        "user_id",
        "archived_at",
        "saved_at",
    ]
    assert "ix_content_item_saved_at" in {
        index.name for index in item.indexes
    }
    assert "ix_ingest_dispatch_created_item" in {
        index.name for index in IngestDispatch.__table__.indexes
    }
