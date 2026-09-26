from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

from bot.config import Settings
from bot.db import DB
from bot.handlers import core


def ctx(tmp_path, phone="919526000000", allowed=()):
    s = Settings()
    s.owner_phone, s.allowed_user_ids = phone, set(allowed)
    return SimpleNamespace(bot_data={"settings": s, "db": DB(tmp_path / "a.db")}, args=[])


def update(user_id, contact=None, text=None):
    msg = SimpleNamespace(contact=contact, text=text, chat_id=user_id, reply_text=AsyncMock())
    return SimpleNamespace(
        message=msg, effective_message=msg, callback_query=None,
        effective_user=SimpleNamespace(id=user_id, username="u", full_name="Owner", first_name="O"),
        effective_chat=SimpleNamespace(id=user_id, type="private"))


async def test_owner_phone_verifies(tmp_path):
    c = ctx(tmp_path)
    await core.on_contact(update(7, SimpleNamespace(user_id=7, phone_number="+91 95260 00000")), c)
    assert c.bot_data["db"].is_verified(7)


async def test_forwarded_contact_rejected(tmp_path):
    c = ctx(tmp_path)
    await core.on_contact(update(8, SimpleNamespace(user_id=7, phone_number="+919526000000")), c)
    assert not c.bot_data["db"].is_verified(8)


async def test_wrong_phone_rejected(tmp_path):
    c = ctx(tmp_path)
    await core.on_contact(update(9, SimpleNamespace(user_id=9, phone_number="+10000000000")), c)
    assert not c.bot_data["db"].is_verified(9)


async def test_gate_blocks_strangers_but_allows_start(tmp_path):
    c = ctx(tmp_path, allowed={1})
    await core.auth_gate(update(1, text="/positions"), c)       # allowed id passes
    await core.auth_gate(update(2, text="/start"), c)           # stranger may start verification
    with pytest.raises(ApplicationHandlerStop):
        await core.auth_gate(update(2, text="/positions"), c)


async def test_gate_blocks_anonymous_updates(tmp_path):
    u = update(1, text="/start")
    u.effective_user = None
    with pytest.raises(ApplicationHandlerStop):
        await core.auth_gate(u, ctx(tmp_path))
