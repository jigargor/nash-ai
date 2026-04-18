import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Installation


@pytest.mark.anyio
async def test_db_session_can_write_and_read_within_transaction(db_session: AsyncSession) -> None:
    await db_session.execute(
        text("SELECT set_config('app.current_installation_id', :installation_id, true)"),
        {"installation_id": "987654"},
    )
    installation = Installation(
        installation_id=987654,
        account_login="integration-test",
        account_type="Organization",
    )
    db_session.add(installation)
    await db_session.flush()

    persisted = await db_session.scalar(
        select(Installation).where(Installation.installation_id == installation.installation_id)
    )

    assert persisted is not None
    assert persisted.account_login == "integration-test"
