from types import SimpleNamespace

import pytest
from telegram.ext import ApplicationHandlerStop

from app.bot import gate


def _ctx():
    return SimpleNamespace(bot_data={"cfg": SimpleNamespace(owner_id=42)})


async def test_gate_allows_owner():
    assert await gate(SimpleNamespace(effective_user=SimpleNamespace(id=42)), _ctx()) is None


@pytest.mark.parametrize("user", [SimpleNamespace(id=7), None])
async def test_gate_blocks_others(user):
    with pytest.raises(ApplicationHandlerStop):
        await gate(SimpleNamespace(effective_user=user), _ctx())
