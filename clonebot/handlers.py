"""Neutral V2 clone runtime with a clean force-subscribe gate."""
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from database.engine import AsyncSessionLocal, select
from database.models import BotChannel, CloneUser
from keyboards import BLUE, GREEN, EMOJI_CHECK, EMOJI_DEVIL, btn
from utils.fsub import missing_channels

log = logging.getLogger("nexora.clonebot")


async def _required_channels(client: Client, bot_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BotChannel)
            .where(BotChannel.bot_id == bot_id, BotChannel.required.is_(True))
            .order_by(BotChannel.position.asc(), BotChannel.id.asc())
        )
        return list(result.scalars().all())


async def _show_gate(client: Client, target, user_id: int) -> bool:
    bot_id = int(getattr(client, "bot_db_id", 0))
    if not bot_id:
        return False

    channels = await _required_channels(client, bot_id)
    missing = await missing_channels(client, channels, user_id)
    if not missing:
        return False

    rows = []
    for channel in missing:
        label = channel.title or channel.username or f"Channel {channel.id}"
        link = f"https://t.me/{channel.username}" if channel.username else None
        if link:
            rows.append([btn(BLUE, f"Join {label}", url=link, icon=EMOJI_DEVIL)])
        else:
            rows.append([btn(BLUE, label, "fsub:info", icon=EMOJI_DEVIL)])
    rows.append([btn(GREEN, "Verify Membership", "fsub:verify", icon=EMOJI_CHECK)])

    text = (
        "**Quick verification**\n\n"
        "> Join every channel shown below.\n"
        "> When you finish, press **Verify Membership**.\n\n"
        f"→ Remaining: **{len(missing)}**"
    )
    try:
        if getattr(target, "photo", None):
            await target.edit_caption(text, reply_markup=InlineKeyboardMarkup(rows))
        else:
            await target.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
    except RPCError:
        await target.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))
    return True


async def _mark_verified(client: Client, user: Message | CallbackQuery) -> None:
    bot_id = int(getattr(client, "bot_db_id", 0))
    from_user = user.from_user
    if not bot_id or from_user is None:
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CloneUser).where(
                CloneUser.bot_id == bot_id,
                CloneUser.user_id == from_user.id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(
                CloneUser(
                    bot_id=bot_id,
                    user_id=from_user.id,
                    username=from_user.username,
                    name=from_user.first_name,
                    verified=True,
                )
            )
        else:
            row.verified = True
            row.username = from_user.username
            row.name = from_user.first_name
        await session.commit()


def register_clone_handlers(app: Client) -> None:
    @app.on_message(filters.command("start") & filters.private)
    async def start(client: Client, message: Message) -> None:
        if await _show_gate(client, message, message.from_user.id):
            return
        await _mark_verified(client, message)
        await message.reply_text(
            "**Nexora V2 Bot**\n\n"
            "> This runtime is ready for a released template.\n\n"
            "→ Public commands are shown in the Telegram bot menu.\n"
            "→ Owner/admin controls are kept separate."
        )

    @app.on_message(filters.command("help") & filters.private)
    async def help_cmd(client: Client, message: Message) -> None:
        if await _show_gate(client, message, message.from_user.id):
            return
        await message.reply_text(
            "**Help**\n\n"
            "> This bot is running on the Nexora V2 runtime.\n"
            "→ Use the command menu to see public features."
        )

    @app.on_callback_query(filters.regex("^fsub:"))
    async def fsub_callback(client: Client, cq: CallbackQuery) -> None:
        if cq.data == "fsub:info":
            await cq.answer(
                "Join this channel manually, then return and verify.",
                show_alert=True,
            )
            return

        if await _show_gate(client, cq.message, cq.from_user.id):
            await cq.answer("Some channels are still missing.", show_alert=True)
            return

        await _mark_verified(client, cq)
        await cq.answer("Verification complete.", show_alert=False)
        try:
            await cq.message.edit_text(
                "**Verification complete**\n\n"
                "> You are verified for this bot.\n\n"
                "→ Use /start to open the bot."
            )
        except RPCError:
            pass
