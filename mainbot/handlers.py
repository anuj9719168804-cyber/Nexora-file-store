"""Nexora Bot Factory main bot handlers.

Public commands are configured separately from owner controls.
"""
from __future__ import annotations

import logging
import datetime as dt

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import BotCommand, CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from bot_manager import manager
from clonebot.handlers import register_clone_handlers
from config import settings
from database.engine import AsyncSessionLocal
from database.models import Bot as BotModel
from database.models import (
    BotSettings, CloneUser, MainBotChannel, Owner,
    NexoraGiftCode, NexoraPaymentOrder, NexoraReferral,
    NexoraWallet, NexoraWalletTransaction,
)
from keyboards import (
    BLUE, DANGER, DEFAULT, GREEN, PRIMARY, RED, SUCCESS, YELLOW,
    EMOJI_BELL, EMOJI_CHART, EMOJI_CHECK, EMOJI_CROWN, EMOJI_DEVIL,
    EMOJI_FIRE, EMOJI_FLAG_IN, EMOJI_FOLDER, EMOJI_GLOBE, EMOJI_GUARD,
    EMOJI_LINK, EMOJI_MIC, EMOJI_OCTAGON, EMOJI_PHONE, EMOJI_SIREN,
    EMOJI_SPARKLE, EMOJI_STOP, EMOJI_TOOLS, EMOJI_TRASH, EMOJI_TROPHY, EMOJI_X, EMOJI_STAR,
    IMG_ADMIN, IMG_CLONE, IMG_WELCOME,
    SUPPORT_URL,
    TXT_ERR, TXT_INFO, TXT_OK, TXT_WARN,
    admin_menu_kb, back_kb, btn, main_menu_kb, quote,
    template_kb, yes_no_kb,
)
from utils.economy import credit, create_referral, get_economy_settings, get_wallet, new_gift_code, qualify_referral, redeem_code
from utils.fsub import missing_channels
from utils.state import PendingAction, main_pending
from utils.notify import notify_owner, notify_public, notify_main_log

log = logging.getLogger("nexora.mainbot")

# Public command menu for the main Factory bot.
# Owner/admin controls are intentionally excluded.
PUBLIC_COMMANDS = [
    BotCommand("start", "Open the Nexora Factory"),
    BotCommand("help", "How Nexora works"),
    BotCommand("balance", "View your coin balance"),
    BotCommand("refer", "Open your referral center"),
    BotCommand("redeem", "Redeem a gift code"),
]

# ── Text constants ────────────────────────────────────────────────────────────
WELCOME_TEXT = (
    "**Nex Bot Factory**\n\n"
    "> Build and deploy Telegram bots from one clean control panel.\n\n"
    "→ Templates\n"
    "→ Fast deployment\n"
    "→ Nexora Coins\n"
    "→ Referrals and redeem codes\n"
    "→ Manual UPI purchases\n\n"
    "Use the buttons below to continue."
)

HELP_TEXT = (
    "**How it works**\n\n"
    "> 1. Create your bot with @BotFather.\n"
    "> 2. Send the token here.\n"
    "> 3. Choose a released template.\n"
    "> 4. Nexora configures the BotFather command menu automatically.\n\n"
    "The legacy clone templates are hidden while the V2 registry is rebuilt."
)

SUPPORT_TEXT = f"**Nexora Support**\n\n> Need help?\n→ {SUPPORT_URL}"

def _template_label(bot_type: str | None) -> str:
    """Resolve display metadata from the V2 registry only."""
    if not bot_type:
        return "Nexora V2"
    from templates.registry import get_template
    template = get_template(bot_type)
    return template.name if template else "Nexora V2"


BOT_ABOUT = "Powered by Nexora · {main_username}"


def _is_main_owner(user_id: int) -> bool:
    return user_id == settings.main_owner_id


async def _log_main(client: Client, text: str, *, public: bool = True) -> None:
    """Write platform events to the owner log and, when safe, the public log."""
    await notify_main_log(text)
    if public:
        await notify_public(text)


async def _get_or_create_owner(session, user) -> Owner:
    result = await session.execute(select(Owner).where(Owner.telegram_id == user.id))
    owner = result.scalar_one_or_none()
    if owner is None:
        owner = Owner(telegram_id=user.id, username=user.username, first_name=user.first_name)
        session.add(owner)
        await session.flush()
    return owner


async def _configure_clone_bot_profile(
    clone_client: Client, bot_type: str, main_username: str
) -> None:
    """Configure only public BotFather commands from the V2 template manifest."""
    from templates.registry import get_template

    template = get_template(bot_type)
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help"),
    ]
    description = "Nexora V2 Telegram bot."
    if template:
        commands.extend(
            BotCommand(item.command, item.description)
            for item in template.commands
            if item.command not in {"owner", "admin"}
        )
        description = template.description

    try:
        await clone_client.set_bot_commands(commands)
        await clone_client.set_bot_description(description)
        await clone_client.set_bot_short_description(
            BOT_ABOUT.format(main_username=f"@{main_username}")
        )
    except Exception:
        log.warning("Could not configure clone profile", exc_info=True)



async def _get_wallet_view(user_id: int) -> tuple[int, int, int]:
    async with AsyncSessionLocal() as session:
        wallet = await get_wallet(session, user_id)
        await session.commit()
        return wallet.balance, wallet.lifetime_earned, wallet.lifetime_spent


async def _send_balance(target, user_id: int) -> None:
    balance, earned, spent = await _get_wallet_view(user_id)
    text = (
        "**Nexora Balance**\n\n"
        f"> Available\n**{balance:,} coins**\n\n"
        f"→ Earned: **{earned:,} coins**\n"
        f"→ Spent: **{spent:,} coins**\n\n"
        "Choose an action below."
    )
    markup = InlineKeyboardMarkup([
        [btn(SUCCESS, "Add Balance", "balance:add", icon=EMOJI_FLAG_IN)],
        [
            btn(DEFAULT, "Gift Code", "redeem", icon=EMOJI_CHECK),
            btn(DEFAULT, "Transactions", "balance:tx", icon=EMOJI_SIREN),
        ],
        [btn(DEFAULT, "Referrals", "referrals", icon=EMOJI_STAR)],
        [btn(DANGER, "Back", "home", icon=EMOJI_OCTAGON)],
    ])
    try:
        await target.edit_text(text, reply_markup=markup)
    except RPCError:
        await target.reply_text(text, reply_markup=markup)


async def _send_transactions(target, user_id: int) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(NexoraWalletTransaction)
            .where(NexoraWalletTransaction.user_id == user_id)
            .order_by(NexoraWalletTransaction.created_at.desc())
            .limit(12)
        )
        rows = result.scalars().all()
    lines = ["**Transactions**", "", "> Latest coin activity"]
    if not rows:
        lines.append("→ No transactions yet.")
    for row in rows:
        sign = "+" if row.amount > 0 else ""
        lines.append(f"→ **{sign}{row.amount:,}** · {row.note or row.kind.replace('_', ' ').title()}")
    try:
        await target.edit_text("\n".join(lines), reply_markup=back_kb("balance"))
    except RPCError:
        await target.reply_text("\n".join(lines), reply_markup=back_kb("balance"))


async def _send_referrals(client: Client, target, user_id: int) -> None:
    me = await client.get_me()
    async with AsyncSessionLocal() as session:
        economy = await get_economy_settings(session)
        invited = await session.scalar(
            select(func.count()).select_from(NexoraReferral).where(
                NexoraReferral.referrer_user_id == user_id
            )
        ) or 0
        qualified = await session.scalar(
            select(func.count()).select_from(NexoraReferral).where(
                NexoraReferral.referrer_user_id == user_id,
                NexoraReferral.qualified.is_(True),
            )
        ) or 0
    link = f"https://t.me/{me.username}?start=ref_{user_id}"
    text = (
        "**Referral Center**\n\n"
        "> Invite friends with your personal link.\n\n"
        f"→ Qualified: **{qualified} / {invited}**\n"
        f"→ Your reward: **{economy.referral_reward} coins**\n"
        f"→ New-user bonus: **{economy.referred_reward} coins**\n\n"
        f"→ Link: {link}"
    )
    markup = InlineKeyboardMarkup([
        [btn(PRIMARY, "Share Link", url=f"https://t.me/share/url?url={link}", icon=EMOJI_STAR)],
        [btn(DANGER, "Back", "home", icon=EMOJI_OCTAGON)],
    ])
    try:
        await target.edit_text(text, reply_markup=markup)
    except RPCError:
        await target.reply_text(text, reply_markup=markup)


async def _send_templates(target) -> None:
    from templates.registry import available_templates
    templates = available_templates()
    if not templates:
        text = (
            "**Template Marketplace**\n\n"
            "> The V2 catalog is being rebuilt.\n\n"
            "→ Legacy templates are retired and hidden.\n"
            "→ New templates will appear here when released."
        )
        markup = back_kb()
    else:
        rows = []
        lines = ["**Template Marketplace**", "", "> Released templates"]
        for item in templates:
            lines.append(f"→ **{item.name}** · {item.description}")
            rows.append([btn(PRIMARY, item.name, f"tpl:{item.slug}", icon=EMOJI_SPARKLE)])
        rows.append([btn(DANGER, "Back", "home", icon=EMOJI_OCTAGON)])
        text = "\n".join(lines)
        markup = InlineKeyboardMarkup(rows)
    try:
        await target.edit_text(text, reply_markup=markup)
    except RPCError:
        await target.reply_text(text, reply_markup=markup)


async def _redeem_code(message: Message, code: str) -> None:
    async with AsyncSessionLocal() as session:
        ok, reason, coins = await redeem_code(session, message.from_user.id, code)
        wallet = await get_wallet(session, message.from_user.id)
        await session.commit()
        balance = wallet.balance
    if not ok:
        await message.reply_text(
            f"**Gift Code**\n\n> {reason}",
            reply_markup=back_kb("balance"),
        )
        return
    await notify_main_log(
        f"Gift code redeemed\n→ User: {message.from_user.id}\n→ Coins: {coins}"
    )
    await message.reply_text(
        f"**Code accepted**\n\n> Added **{coins} coins**.\n→ Balance: **{balance} coins**",
        reply_markup=back_kb("balance"),
    )


async def _handle_utr(message: Message) -> None:
    pending = main_pending.pop(message.from_user.id, None)
    if not pending:
        return
    utr = message.text.strip()
    if len(utr) < 6:
        main_pending[message.from_user.id] = pending
        await message.reply_text(
            "**UTR not accepted**\n\n> Send the UPI transaction reference number.",
            reply_markup=back_kb("balance:add"),
        )
        return

    coins = int(pending.data["coins"])
    amount = int(pending.data["amount"])
    async with AsyncSessionLocal() as session:
        order = NexoraPaymentOrder(
            user_id=message.from_user.id,
            coins=coins,
            amount_inr=amount,
            utr=utr,
            status="pending",
        )
        session.add(order)
        await session.flush()
        order_id = order.id
        await session.commit()

    await notify_owner(
        f"New UPI payment\n→ Order: #{order_id}\n→ User: {message.from_user.id}\n"
        f"→ Amount: ₹{amount}\n→ Coins: {coins}\n→ UTR: {utr}"
    )
    await notify_main_log(
        f"UPI payment submitted\n→ Order: #{order_id}\n→ Amount: ₹{amount}\n→ Coins: {coins}"
    )
    await notify_public(f"UPI payment submitted · order #{order_id} · {coins} coins")
    await message.reply_text(
        f"**Payment submitted**\n\n> Order: #{order_id}\n> Status: **Pending review**\n\n"
        "→ Coins are added after the UTR is approved by the main owner.",
        reply_markup=back_kb("balance"),
    )


async def _handle_gift_code(message: Message) -> None:
    pending = main_pending.pop(message.from_user.id, None)
    if not pending:
        return
    parts = message.text.strip().split()
    try:
        coins = int(parts[0])
        uses = int(parts[1]) if len(parts) > 1 else 1
        days = int(parts[2]) if len(parts) > 2 else 0
        if coins <= 0 or uses <= 0 or days < 0:
            raise ValueError
    except (ValueError, IndexError):
        await message.reply_text(
            "**Gift Code Setup**\n\n> Format: coins uses days\n→ Example: 500 10 7",
            reply_markup=back_kb("adm:economy"),
        )
        return

    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days) if days else None
    expiry_label = "none" if not days else f"{days} day(s)"
    async with AsyncSessionLocal() as session:
        code = new_gift_code()
        session.add(
            NexoraGiftCode(
                code=code,
                coins=coins,
                max_uses=uses,
                expires_at=expires,
            )
        )
        await session.commit()

    await notify_main_log(
        f"Gift code created\n→ Code: {code}\n→ Coins: {coins}\n→ Uses: {uses}"
    )
    await message.reply_text(
        f"**Gift code created**\n\n→ Code: {code}\n→ Value: **{coins} coins**\n"
        f"→ Uses: **{uses}**\n→ Expiry: **{expiry_label}**",
        reply_markup=back_kb("adm:economy"),
    )


async def _handle_reward_setting(message: Message, action: str) -> None:
    main_pending.pop(message.from_user.id, None)
    try:
        value = int(message.text.strip())
        if value < 0 or value > 1000000:
            raise ValueError
    except ValueError:
        await message.reply_text(
            "**Invalid reward**\n\n> Send a whole number from 0 to 1,000,000.",
            reply_markup=back_kb("adm:economy"),
        )
        return
    async with AsyncSessionLocal() as session:
        economy = await get_economy_settings(session)
        if action == "await_referral_reward":
            economy.referral_reward = value
            label = "referrer reward"
        else:
            economy.referred_reward = value
            label = "new-user bonus"
        await session.commit()
    await message.reply_text(
        f"**Economy updated**\n\n→ {label}: **{value} coins**",
        reply_markup=back_kb("adm:economy"),
    )


async def _review_payment(client: Client, cq: CallbackQuery, order_id: int, reviewer: int, approve: bool) -> None:
    async with AsyncSessionLocal() as session:
        order = await session.get(NexoraPaymentOrder, order_id, with_for_update=True)
        if order is None or order.status != "pending":
            await cq.answer("This order is already reviewed.", show_alert=True)
            return
        order.status = "approved" if approve else "rejected"
        order.reviewed_by = reviewer
        order.reviewed_at = dt.datetime.now(dt.timezone.utc)
        balance = None
        if approve:
            wallet = await credit(
                session,
                order.user_id,
                order.coins,
                kind="upi",
                reference=str(order.id),
                note=f"UPI order #{order.id} approved",
            )
            balance = wallet.balance
        await session.commit()
    try:
        if approve:
            await client.send_message(
                order.user_id,
                f"**Payment approved**\n\n> Order #{order.id} is verified.\n"
                f"→ Added **{order.coins} coins**.\n→ Balance: **{balance} coins**",
            )
        else:
            await client.send_message(
                order.user_id,
                f"**Payment rejected**\n\n> Order #{order.id} was not approved.\n"
                "→ Contact support if you believe this is incorrect.",
            )
    except RPCError:
        pass
    await notify_main_log(
        f"UPI order reviewed\n→ Order: #{order.id}\n→ Result: {'approved' if approve else 'rejected'}\n→ Reviewer: {reviewer}"
    )
    await cq.message.edit_text(
        f"**Order #{order.id} reviewed**\n\n→ Result: **{'Approved' if approve else 'Rejected'}**",
        reply_markup=back_kb("adm:payments"),
    )


def register_main_handlers(app: Client) -> None:

    # ── /start ────────────────────────────────────────────────────────────────
    @app.on_message(filters.command("start") & filters.private)
    async def start_cmd(client: Client, message: Message) -> None:
        user = message.from_user
        main_pending.pop(user.id, None)

        # ── Register the user and capture a referral before FSub ────────────────
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Owner).where(Owner.telegram_id == user.id))
            owner = result.scalar_one_or_none()
            is_new = owner is None
            if owner is None:
                session.add(
                    Owner(
                        telegram_id=user.id,
                        username=user.username,
                        first_name=user.first_name,
                    )
                )
                await session.flush()
            if is_new and message.command and len(message.command) > 1:
                payload = message.command[1]
                if payload.startswith("ref_"):
                    try:
                        referrer_id = int(payload.split("_", 1)[1])
                    except ValueError:
                        referrer_id = 0
                    if referrer_id:
                        await create_referral(session, referrer_id, user.id)
            await session.commit()

        # ── Main-bot force-subscribe check ────────────────────────────────────
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(MainBotChannel))
            main_channels = result.scalars().all()

        if main_channels:
            missing = await missing_channels(client, list(main_channels), user.id)
            if missing:
                rows = []
                for ch in missing:
                    label = ch.title or ch.username or "Channel"
                    link  = f"https://t.me/{ch.username}" if ch.username else None
                    rows.append([
                        btn(BLUE, f"Join {label}", url=link, icon=EMOJI_DEVIL)
                        if link else btn(BLUE, label, "noop_main", icon=EMOJI_DEVIL)
                    ])
                rows.append([btn(GREEN, "Verify Membership", "main_verify", icon=EMOJI_CHECK)])
                caption = (
                    "**Quick verification**\n\n"
                    "> Join every channel shown below.\n"
                    "> When you finish, press **Verify Membership**.\n\n"
                    f"→ Remaining: **{len(missing)}**"
                )
                try:
                    await message.reply_photo(IMG_WELCOME, caption=caption,
                                              reply_markup=InlineKeyboardMarkup(rows))
                except RPCError:
                    await message.reply_text(caption, reply_markup=InlineKeyboardMarkup(rows))
                return

        # ── First-time user notification ──────────────────────────────────────
        if is_new:
            handle = f"@{user.username}" if user.username else f"id:{user.id}"
            await notify_owner(
                f"👤 **New user** started the main bot\n"
                f"Name: {user.first_name}\n"
                f"Username: {handle}\n"
                f"ID: `{user.id}`"
            )

        async with AsyncSessionLocal() as session:
            referral = await qualify_referral(session, user.id)
            await session.commit()
        if referral:
            referrer_id, amount = referral
            await notify_owner(
                f"Referral qualified\n→ Referrer: {referrer_id}\n→ User: {user.id}\n→ Reward: {amount} coins"
            )
            try:
                await client.send_message(
                    referrer_id,
                    f"**Referral qualified**\n\n> Your invite completed verification.\n→ **+{amount} coins** added.",
                )
            except RPCError:
                pass

        try:
            await message.reply_photo(IMG_WELCOME, caption=WELCOME_TEXT, reply_markup=main_menu_kb())
        except RPCError:
            await message.reply_text(WELCOME_TEXT, reply_markup=main_menu_kb())

    # ── /help ─────────────────────────────────────────────────────────────────
    @app.on_message(filters.command("help") & filters.private)
    async def help_cmd(client: Client, message: Message) -> None:
        await message.reply_text(HELP_TEXT, reply_markup=back_kb())

    # ── /support ──────────────────────────────────────────────────────────────
    @app.on_message(filters.command("support") & filters.private)
    async def support_cmd(client: Client, message: Message) -> None:
        await message.reply_text(SUPPORT_TEXT, reply_markup=back_kb())

    # ── economy commands ───────────────────────────────────────────────────────
    @app.on_message(filters.command("balance") & filters.private)
    async def balance_cmd(client: Client, message: Message) -> None:
        await _send_balance(message, message.from_user.id)

    @app.on_message(filters.command("refer") & filters.private)
    async def refer_cmd(client: Client, message: Message) -> None:
        await _send_referrals(client, message, message.from_user.id)

    @app.on_message(filters.command("redeem") & filters.private)
    async def redeem_cmd(client: Client, message: Message) -> None:
        if len(message.command) > 1:
            await _redeem_code(message, message.command[1])
            return
        main_pending[message.from_user.id] = PendingAction("await_redeem")
        await message.reply_text(
            "**Redeem Gift Code**\n\n> Send your code in the next message.",
            reply_markup=back_kb("balance"),
        )

    # ── /newbot ───────────────────────────────────────────────────────────────
    @app.on_message(filters.command("newbot") & filters.private)
    async def newbot_cmd(client: Client, message: Message) -> None:
        main_pending[message.from_user.id] = PendingAction("await_token")
        await message.reply_text(
            f"{TXT_INFO} ✨ Send me the **bot token** you copied from @BotFather.",
            reply_markup=back_kb(),
        )

    # ── /mybots ───────────────────────────────────────────────────────────────
    @app.on_message(filters.command("mybots") & filters.private)
    async def mybots_cmd(client: Client, message: Message) -> None:
        await _send_mybots(client, message.from_user.id, message)

    # ── /rmbot ────────────────────────────────────────────────────────────────
    @app.on_message(filters.command("rmbot") & filters.private)
    async def rmbot_cmd(client: Client, message: Message) -> None:
        await _send_rmbot_list(client, message.from_user.id, message)

    # ── /admin ────────────────────────────────────────────────────────────────
    @app.on_message(filters.command("admin") & filters.private)
    async def admin_cmd(client: Client, message: Message) -> None:
        if not _is_main_owner(message.from_user.id):
            return
        try:
            await message.reply_photo(
                IMG_ADMIN,
                caption="**Nexora Control Room**\n\n> Main-owner controls only.",
                reply_markup=admin_menu_kb(),
            )
        except RPCError:
            await message.reply_text(
                "**Nexora Control Room**\n\n> Main-owner controls only.",
                reply_markup=admin_menu_kb(),
            )

    # ── helpers ───────────────────────────────────────────────────────────────
    async def _send_mybots(client: Client, user_id: int, target) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(BotModel).join(Owner).where(Owner.telegram_id == user_id)
            )
            bots = result.scalars().all()

        if not bots:
            try:
                await target.edit_text(
                    "**My Bots**\n\n> You have not connected a bot yet.\n→ Use Create Bot to get started.",
                    reply_markup=back_kb(),
                )
            except RPCError:
                await target.reply_text(
                    "**My Bots**\n\n> You have not connected a bot yet.\n→ Use Create Bot to get started.",
                    reply_markup=back_kb(),
                )
            return

        rows = []
        for b in bots:
            label = f"@{b.bot_username}" if b.bot_username else (b.bot_name or f"Bot #{b.id}")
            icon = EMOJI_GUARD
            rows.append([btn(SUCCESS, label, f"openpanel:{b.id}", icon=icon)])
        rows.append([btn(DANGER, "Back", "home", icon=EMOJI_OCTAGON)])
        try:
            await target.edit_text(
                f"**My Bots**\n\n> Connected bots: **{len(bots)}**", reply_markup=InlineKeyboardMarkup(rows)
            )
        except RPCError:
            await target.reply_text(
                f"**My Bots**\n\n> Connected bots: **{len(bots)}**", reply_markup=InlineKeyboardMarkup(rows)
            )

    async def _send_rmbot_list(client: Client, user_id: int, target) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(BotModel).join(Owner).where(Owner.telegram_id == user_id)
            )
            bots = result.scalars().all()

        if not bots:
            try:
                "**Remove a Bot**\n\n> You have no connected bots.",
            except RPCError:
                "**Remove a Bot**\n\n> You have no connected bots.",
            return

        rows = []
        for b in bots:
            label = f"@{b.bot_username}" if b.bot_username else (b.bot_name or f"Bot #{b.id}")
            rows.append([btn(DANGER, f"Delete {label}", f"rmbot:{b.id}", icon=EMOJI_TRASH)])
        rows.append([btn(PRIMARY, "Back", "home", icon=EMOJI_OCTAGON)])
        try:
            await target.edit_text(
                "**Remove a Bot**\n\n> Choose the bot you want to disconnect.",
            )
        except RPCError:
            await target.reply_text(
                "**Remove a Bot**\n\n> Choose the bot you want to disconnect.",
            )

    # ── text router ───────────────────────────────────────────────────────────
    @app.on_message(
        filters.private & filters.text
        & ~filters.command(["start", "help", "newbot", "mybots", "rmbot", "support", "admin", "balance", "refer", "redeem"])
    )
    async def text_router(client: Client, message: Message) -> None:
        pending = main_pending.get(message.from_user.id)
        if not pending:
            return
        if pending.action == "await_token":
            await _handle_new_token(client, message)
        elif pending.action == "await_redeem":
            main_pending.pop(message.from_user.id, None)
            await _redeem_code(message, message.text.strip())
        elif pending.action == "await_utr":
            await _handle_utr(message)
        elif pending.action == "await_gift":
            await _handle_gift_code(message)
        elif pending.action in {"await_referral_reward", "await_referred_reward"}:
            await _handle_reward_setting(message, pending.action)
        elif pending.action == "await_admin_broadcast":
            await _handle_admin_broadcast(client, message)
        elif pending.action == "await_main_fsub_channel":
            await _handle_main_fsub_add(client, message)

    async def _handle_new_token(client: Client, message: Message) -> None:
        token = message.text.strip()
        if ":" not in token or len(token.split(":")[0]) < 5:
            await message.reply_text(
                "**Token check failed**\n\n> Send the exact token from @BotFather.",
                "**Token check failed**\n\n> Send the exact token from @BotFather.",
                reply_markup=back_kb(),
            )
            return

        status_msg = await message.reply_text("**Checking token**\n\n> Connecting to Telegram…")

        probe = Client(
            name=f"probe_{message.from_user.id}",
            api_id=settings.api_id,
            api_hash=settings.api_hash,
            bot_token=token,
            in_memory=True,
        )
        try:
            await probe.start()
            me = await probe.get_me()
        except Exception:
            try:
                await probe.stop()
            except Exception:
                pass
            await status_msg.edit_text(
                f"{TXT_ERR} Telegram rejected that token. Double-check it and try again.",
                reply_markup=back_kb(),
            )
            return
        await probe.stop()

        async with AsyncSessionLocal() as session:
            existing = await session.execute(select(BotModel).where(BotModel.bot_token == token))
            if existing.scalar_one_or_none() is not None:
                await status_msg.edit_text(
                    f"{TXT_ERR} This bot is already registered with Nexora.",
                    reply_markup=back_kb(),
                )
                return

        from templates.registry import available_templates
        templates = available_templates()
        if not templates:
            main_pending.pop(message.from_user.id, None)
            await status_msg.edit_text(
                f"**@{me.username} verified**\n\n"
                "> The V2 marketplace has no released templates yet.\n\n"
                "→ Your token is valid and was not stored.\n"
                "→ Return to **Templates** when a release is published.",
                reply_markup=back_kb(),
            )
            return

        main_pending[message.from_user.id] = PendingAction(
            "await_template",
            {
                "token": token,
                "username": me.username,
                "name": me.first_name or me.username or "Nexora Bot",
            },
        )
        rows = [
            [btn(PRIMARY, item.name, f"tpl:{item.slug}", icon=EMOJI_SPARKLE)]
            for item in templates
        ]
        rows.append([btn(DANGER, "Cancel", "home", icon=EMOJI_OCTAGON)])
        await status_msg.edit_text(
            f"**@{me.username} verified**\n\n> Choose a released template.",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def _create_bot(
        client: Client, user_id: int, token: str, bot_username: str,
        bot_name: str, bot_type: str, status_msg: Message,
    ) -> None:
        """Create the bot record, start the clone, and report back."""
        async with AsyncSessionLocal() as session:
            existing = await session.execute(select(BotModel).where(BotModel.bot_token == token))
            if existing.scalar_one_or_none() is not None:
                await status_msg.edit_text(
                    f"{TXT_ERR} This bot is already registered.", reply_markup=back_kb()
                )
                return

            async with AsyncSessionLocal() as s2:
                res = await s2.execute(select(Owner).where(Owner.telegram_id == user_id))
                owner = res.scalar_one_or_none()
                if owner is None:
                    owner = Owner(telegram_id=user_id)
                    s2.add(owner)
                    await s2.flush()
                owner_db_id = owner.id
                await s2.commit()

            bot_row = BotModel(
                owner_id=owner_db_id,
                bot_token=token,
                bot_username=bot_username,
                bot_name=bot_name,
                bot_type=bot_type,
                welcome_caption=f"Welcome to {bot_name}",
            )
            session.add(bot_row)
            await session.flush()
            session.add(BotSettings(bot_id=bot_row.id))
            await session.commit()
            new_bot_id = bot_row.id

        main_pending.pop(user_id, None)

        try:
            clone_client = await manager.start_clone(new_bot_id, token, register_clone_handlers)
        except Exception:
            log.exception("Failed to start clone bot %s", new_bot_id)
            await status_msg.edit_text(
                f"{TXT_ERR} Bot saved but failed to start. Try /mybots later.",
                reply_markup=back_kb(),
            )
            return

        # Auto-configure only public commands from the V2 manifest.
        try:
            me = await client.get_me()
            main_username = me.username or "NexoraBot"
            await _configure_clone_bot_profile(clone_client, bot_type, main_username)
        except Exception:
            log.warning("Auto-profile config failed (non-fatal)", exc_info=True)

        type_label = _template_label(bot_type)
        await _log_main(
            client,
            f"New bot created\n→ Template: {type_label}\n→ Owner: {user_id}\n→ Bot: @{bot_username}",
        )
        await notify_owner(
            f"New bot created\n→ Template: {type_label}\n→ Bot: @{bot_username}\n→ Owner: {user_id}"
        )
        await status_msg.edit_text(
            f"**Bot is live**\n\n"
            f"→ @{bot_username}\n"
            f"→ Template: **{type_label}**\n\n"
            "> Public commands have been configured automatically.\n"
            "> Owner/admin controls are kept separate.",
            reply_markup=InlineKeyboardMarkup([
                [btn(SUCCESS, "Open Bot", url=f"https://t.me/{bot_username}", icon=EMOJI_GUARD)],
                [btn(DEFAULT, "My Bots", "mybots", icon=EMOJI_TOOLS)],
            ]),
        )

    # ── callback router ───────────────────────────────────────────────────────
    @app.on_callback_query()
    async def callback_router(client: Client, cq: CallbackQuery) -> None:
        data = cq.data or ""
        user_id = cq.from_user.id

        # ── home ──
        if data == "home":
            main_pending.pop(user_id, None)
            try:
                await cq.message.edit_caption(WELCOME_TEXT, reply_markup=main_menu_kb())
            except RPCError:
                await cq.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())

        # ── main-bot fsub verify ──
        elif data == "main_verify":
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(MainBotChannel))
                main_channels = result.scalars().all()
            missing = await missing_channels(client, list(main_channels), user_id) if main_channels else []
            if missing:
                rows = []
                for ch in missing:
                    label = ch.title or ch.username or "Channel"
                    link = f"https://t.me/{ch.username}" if ch.username else None
                    rows.append([
                        btn(BLUE, f"Join {label}", url=link, icon=EMOJI_DEVIL)
                        if link else btn(BLUE, label, "noop_main", icon=EMOJI_DEVIL)
                    ])
                rows.append([btn(GREEN, "Verify Membership", "main_verify", icon=EMOJI_CHECK)])
                text = (
                    "**Verification pending**\n\n"
                    "> Some channels are still missing.\n"
                    f"→ Remaining: **{len(missing)}**\n"
                    "> Only the remaining channels are shown."
                )
                try:
                    await cq.message.edit_caption(text, reply_markup=InlineKeyboardMarkup(rows))
                except RPCError:
                    await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))
                await cq.answer(f"{len(missing)} channel(s) still required.", show_alert=True)
                return
            try:
                await cq.message.edit_caption(WELCOME_TEXT, reply_markup=main_menu_kb())
            except RPCError:
                await cq.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
            await cq.answer("Verification complete.", show_alert=False)

        elif data == "noop_main":
            await cq.answer("Use the join button above first.", show_alert=True)
            return

        # ── help ──
        elif data == "help":
            try:
                await cq.message.edit_caption(HELP_TEXT, reply_markup=back_kb())
            except RPCError:
                await cq.message.edit_text(HELP_TEXT, reply_markup=back_kb())

        # ── support ──
        elif data == "support":
            try:
                await cq.message.edit_caption(SUPPORT_TEXT, reply_markup=back_kb())
            except RPCError:
                await cq.message.edit_text(SUPPORT_TEXT, reply_markup=back_kb())

        elif data == "balance":
            await _send_balance(cq.message, user_id)

        elif data == "balance:add":
            await cq.message.edit_text(
                "**Add Balance**\n\n"
                "> Manual UPI only.\n"
                "> Choose a package below.\n\n"
                "→ After payment, submit the UTR for review.",
                reply_markup=InlineKeyboardMarkup([
                    [btn(PRIMARY, "100 Coins · ₹10", "upi:100:10", icon=EMOJI_FLAG_IN)],
                    [btn(PRIMARY, "250 Coins · ₹25", "upi:250:25", icon=EMOJI_FLAG_IN)],
                    [btn(PRIMARY, "600 Coins · ₹50", "upi:600:50", icon=EMOJI_FLAG_IN)],
                    [btn(PRIMARY, "1,300 Coins · ₹100", "upi:1300:100", icon=EMOJI_FLAG_IN)],
                    [btn(DANGER, "Back", "balance", icon=EMOJI_OCTAGON)],
                ]),
            )

        elif data.startswith("upi:"):
            _, coins, amount = data.split(":")
            main_pending[user_id] = PendingAction(
                "await_utr",
                {"coins": int(coins), "amount": int(amount)},
            )
            upi = settings.upi_id or "Not configured"
            await cq.message.edit_text(
                "**UPI Payment**\n\n"
                f"→ Amount: **₹{int(amount)}**\n"
                f"→ Coins: **{int(coins):,}**\n"
                f"→ UPI ID: {upi}\n"
                f"→ Name: **{settings.upi_name}**\n\n"
                "> Complete the payment, then send the UTR/reference number here.",
                reply_markup=back_kb("balance:add"),
            )

        elif data == "balance:tx":
            await _send_transactions(cq.message, user_id)

        elif data == "redeem":
            main_pending[user_id] = PendingAction("await_redeem")
            await cq.message.edit_text(
                "**Redeem Gift Code**\n\n> Send the code in your next message.",
                reply_markup=back_kb("balance"),
            )

        elif data == "referrals":
            await _send_referrals(client, cq.message, user_id)

        elif data == "templates":
            await _send_templates(cq.message)

        # ── newbot ──
        elif data == "newbot":
            main_pending[user_id] = PendingAction("await_token")
            try:
                await cq.message.edit_caption(
                    f"{TXT_INFO} ✨ Send me the **bot token** you copied from @BotFather.",
                    reply_markup=back_kb(),
                )
            except RPCError:
                await cq.message.edit_text(
                    f"{TXT_INFO} ✨ Send me the **bot token** you copied from @BotFather.",
                    reply_markup=back_kb(),
                )

        # ── template selection ──
        elif data.startswith("tpl:"):
            pending = main_pending.get(user_id)
            if not pending or pending.action != "await_template":
                await cq.answer("Session expired. Use /newbot again.", show_alert=True)
                return
            bot_type = data.split(":")[1]
            token = pending.data["token"]
            bot_username = pending.data["username"]
            bot_name = pending.data["name"]
            type_label = _template_label(bot_type)
            try:
                await cq.message.edit_text(f"🛠 Creating **{type_label}** bot…")
            except RPCError:
                pass
            await _create_bot(client, user_id, token, bot_username, bot_name, bot_type, cq.message)

        # ── mybots ──
        elif data == "mybots":
            await _send_mybots(client, user_id, cq.message)

        # ── platform stats ──
        elif data == "stats":
            async with AsyncSessionLocal() as session:
                total_owners = await session.scalar(select(func.count()).select_from(Owner)) or 0
                total_bots = await session.scalar(select(func.count()).select_from(BotModel)) or 0
                total_wallets = await session.scalar(select(func.count()).select_from(NexoraWallet)) or 0
            text = (
                "**Platform Statistics**\n\n"
                f"→ Owners: **{total_owners}**\n"
                f"→ Bots: **{total_bots}**\n"
                f"→ Coin wallets: **{total_wallets}**"
            )
            try:
                await cq.message.edit_text(text, reply_markup=back_kb())
            except RPCError:
                await cq.message.edit_caption(text, reply_markup=back_kb())

        # ── open panel ──
        elif data.startswith("openpanel:"):
            b_id = int(data.split(":")[1])
            async with AsyncSessionLocal() as session:
                bot_row = await session.get(BotModel, b_id)
            if bot_row is None:
                await cq.answer("Bot not found.", show_alert=True)
                return
            type_label = _template_label(bot_row.bot_type)
            text = (
                f"💂 **@{bot_row.bot_username}**\n\n"
                f"Type: {type_label}\n\n"
                "→ Public commands are in the bot menu.\n→ Owner controls are kept separate."
            )
            try:
                await cq.message.edit_text(
                    text,
                    reply_markup=InlineKeyboardMarkup([
                        [btn(SUCCESS, "Open Bot",    url=f"https://t.me/{bot_row.bot_username}", icon=EMOJI_GUARD)],
                        [btn(DANGER,  "Delete Bot",  f"rmbot:{bot_row.id}",                      icon=EMOJI_TRASH)],
                        [btn(DEFAULT, "Back",        "mybots",                                   icon=EMOJI_OCTAGON)],
                    ]),
                )
            except RPCError:
                await cq.message.edit_caption(text, reply_markup=InlineKeyboardMarkup([
                    [btn(SUCCESS, "Open Bot",   url=f"https://t.me/{bot_row.bot_username}", icon=EMOJI_GUARD)],
                    [btn(DANGER,  "Delete Bot", f"rmbot:{bot_row.id}",                      icon=EMOJI_TRASH)],
                    [btn(DEFAULT, "Back",       "mybots",                                   icon=EMOJI_OCTAGON)],
                ]))

        # ── rmbot ──
        elif data.startswith("rmbot:"):
            b_id = int(data.split(":")[1])
            async with AsyncSessionLocal() as session:
                bot_row = await session.get(BotModel, b_id)
            if bot_row is None:
                await cq.answer("Bot not found.", show_alert=True)
                return
            label = f"@{bot_row.bot_username}" if bot_row.bot_username else f"Bot #{bot_row.id}"
            try:
                await cq.message.edit_text(
                    f"⛔ Delete **{label}**?\n\nThis removes all its files, links, channels and users.",
                    reply_markup=yes_no_kb(f"rmbot_yes:{b_id}", "mybots"),
                )
            except RPCError:
                pass

        elif data.startswith("rmbot_yes:"):
            b_id = int(data.split(":")[1])
            try:
                async with AsyncSessionLocal() as session:
                    bot_row = await session.get(BotModel, b_id)
                    if bot_row is None:
                        await cq.answer("Already deleted.", show_alert=True)
                        return
                    username = bot_row.bot_username
                    await session.delete(bot_row)
                    await session.commit()
            except Exception:
                log.exception("Failed to delete bot %s", b_id)
                await cq.answer("❌ Delete failed — try again in a moment.", show_alert=True)
                try:
                    await cq.message.edit_text(
                        f"{TXT_ERR} Something went wrong deleting that bot. Please try again.",
                        reply_markup=back_kb(),
                    )
                except RPCError:
                    pass
                return

            try:
                await manager.stop_clone(b_id)
            except Exception:
                log.exception("Failed to stop clone worker for bot %s (db row already deleted)", b_id)
            await _log_main(client, f"🚨 🗑 Clone deleted: @{username} (id {b_id})")
            try:
                await cq.message.edit_text(
                    f"✅ Deleted @{username}.", reply_markup=back_kb()
                )
            except RPCError:
                pass

        elif data == "rmbot_list":
            await _send_rmbot_list(client, user_id, cq.message)

        # ── superadmin panel ──
        elif data.startswith("adm:"):
            if not _is_main_owner(user_id):
                await cq.answer("Access denied.", show_alert=True)
                return
            await _handle_admin_callback(client, cq, data, user_id)

        await cq.answer()

    # ── superadmin callbacks ──────────────────────────────────────────────────
    async def _handle_admin_callback(client: Client, cq: CallbackQuery, data: str, user_id: int) -> None:
        if data == "adm:economy":
            async with AsyncSessionLocal() as session:
                economy = await get_economy_settings(session)
                pending = await session.scalar(
                    select(func.count()).select_from(NexoraPaymentOrder).where(
                        NexoraPaymentOrder.status == "pending"
                    )
                ) or 0
            text = (
                "**Economy Controls**\n\n"
                f"→ Referrer reward: **{economy.referral_reward} coins**\n"
                f"→ New-user bonus: **{economy.referred_reward} coins**\n"
                f"→ Pending UPI orders: **{pending}**\n\n"
                "> Main owner controls these values."
            )
            markup = InlineKeyboardMarkup([
                [
                    btn(PRIMARY, "Referrer Reward", "adm:ref_reward", icon=EMOJI_STAR),
                    btn(PRIMARY, "New-user Bonus", "adm:ref_bonus", icon=EMOJI_STAR),
                ],
                [btn(SUCCESS, "Create Gift Code", "adm:gift", icon=EMOJI_CHECK)],
                [btn(DEFAULT, "Pending Payments", "adm:payments", icon=EMOJI_FLAG_IN)],
                [btn(DANGER, "Back", "adm:home", icon=EMOJI_OCTAGON)],
            ])
            await cq.message.edit_text(text, reply_markup=markup)
            return

        if data == "adm:ref_reward":
            main_pending[user_id] = PendingAction("await_referral_reward")
            await cq.message.edit_text(
                "**Set Referrer Reward**\n\n> Send the coin amount for each qualified referral.",
                reply_markup=back_kb("adm:economy"),
            )
            return

        if data == "adm:ref_bonus":
            main_pending[user_id] = PendingAction("await_referred_reward")
            await cq.message.edit_text(
                "**Set New-user Bonus**\n\n> Send the coin amount for the referred user.",
                reply_markup=back_kb("adm:economy"),
            )
            return

        if data == "adm:gift":
            main_pending[user_id] = PendingAction("await_gift")
            await cq.message.edit_text(
                "**Create Gift Code**\n\n"
                "> Format: coins uses days\n"
                "→ Example: 500 10 7\n"
                "→ Use 0 days for no expiry.",
                reply_markup=back_kb("adm:economy"),
            )
            return

        if data == "adm:payments":
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(NexoraPaymentOrder)
                    .where(NexoraPaymentOrder.status == "pending")
                    .order_by(NexoraPaymentOrder.created_at.asc())
                    .limit(15)
                )
                orders = result.scalars().all()
            if not orders:
                await cq.message.edit_text(
                    "**Pending Payments**\n\n> No UPI payments are waiting for review.",
                    reply_markup=back_kb("adm:economy"),
                )
                return
            rows = []
            lines = ["**Pending Payments**", "", "> Select an order to review"]
            for order in orders:
                lines.append(f"→ #{order.id} · ₹{order.amount_inr} · {order.coins:,} coins")
                rows.append([
                    btn(YELLOW, f"Order #{order.id}", f"adm:pay:{order.id}", icon=EMOJI_FLAG_IN)
                ])
            rows.append([btn(DANGER, "Back", "adm:economy", icon=EMOJI_OCTAGON)])
            await cq.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))
            return

        if data.startswith("adm:pay:"):
            order_id = int(data.split(":")[2])
            async with AsyncSessionLocal() as session:
                order = await session.get(NexoraPaymentOrder, order_id)
            if order is None:
                await cq.answer("Order not found.", show_alert=True)
                return
            text = (
                f"**Payment #{order.id}**\n\n"
                f"→ User: {order.user_id}\n"
                f"→ Amount: ₹{order.amount_inr}\n"
                f"→ Coins: {order.coins:,}\n"
                f"→ UTR: {order.utr or 'missing'}\n"
                f"→ Status: **{order.status}**"
            )
            markup = InlineKeyboardMarkup([
                [
                    btn(SUCCESS, "Approve", f"adm:pay_approve:{order.id}", icon=EMOJI_CHECK),
                    btn(DANGER, "Reject", f"adm:pay_reject:{order.id}", icon=EMOJI_X),
                ],
                [btn(DEFAULT, "Back", "adm:payments", icon=EMOJI_OCTAGON)],
            ])
            await cq.message.edit_text(text, reply_markup=markup)
            return

        if data.startswith("adm:pay_approve:"):
            await _review_payment(client, cq, int(data.split(":")[2]), user_id, True)
            return

        if data.startswith("adm:pay_reject:"):
            await _review_payment(client, cq, int(data.split(":")[2]), user_id, False)
            return

        if data == "adm:fsub":
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(MainBotChannel))
                channels = result.scalars().all()

            lines = ["**Main Bot Verification Channels**\n"]
            rows = []
            if not channels:
                lines.append("> No channels configured.")
            for ch in channels:
                label = ch.title or ch.username or str(ch.chat_id)
                lines.append(f"→ {label}")
                rows.append([btn(DANGER, f"Remove {label}", f"adm:fsub_rm:{ch.id}", icon=EMOJI_TRASH)])
            rows.append([btn(SUCCESS, "Add Channel",  "adm:fsub_add", icon=EMOJI_SPARKLE)])
            rows.append([btn(DANGER,  "Back",         "adm:home",     icon=EMOJI_OCTAGON)])
            try:
                await cq.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))
            except RPCError:
                pass
            return

        if data == "adm:fsub_add":
            main_pending[user_id] = PendingAction("await_main_fsub_channel")
            try:
                await cq.message.edit_text(
                    "**Add Verification Channel**\n\n"
                    "> Forward a channel message or send its username.\n"
                    "→ The main bot must be an admin there first.",
                    reply_markup=InlineKeyboardMarkup([[btn(DANGER, "Cancel", "adm:fsub", icon=EMOJI_OCTAGON)]]),
                )
            except RPCError:
                pass
            return

        if data.startswith("adm:fsub_rm:"):
            ch_id = int(data.split(":")[2])
            async with AsyncSessionLocal() as session:
                ch = await session.get(MainBotChannel, ch_id)
                if ch:
                    await session.delete(ch)
                    await session.commit()
            await _handle_admin_callback(client, cq, "adm:fsub", user_id)
            return

        if data == "adm:stats":
            async with AsyncSessionLocal() as session:
                owners = await session.scalar(select(func.count()).select_from(Owner)) or 0
                bots = await session.scalar(select(func.count()).select_from(BotModel)) or 0
                wallets = await session.scalar(select(func.count()).select_from(NexoraWallet)) or 0
                payments = await session.scalar(
                    select(func.count()).select_from(NexoraPaymentOrder).where(
                        NexoraPaymentOrder.status == "pending"
                    )
                ) or 0
                referrals = await session.scalar(select(func.count()).select_from(NexoraReferral)) or 0
            await cq.message.edit_text(
                "**Platform Statistics**\n\n"
                f"→ Owners: **{owners}**\n"
                f"→ Bots: **{bots}**\n"
                f"→ Coin wallets: **{wallets}**\n"
                f"→ Referrals: **{referrals}**\n"
                f"→ Pending payments: **{payments}**",
                reply_markup=back_kb("adm:home"),
            )

        elif data == "adm:home":
            try:
                await cq.message.edit_text(
                "**Nexora Control Room**\n\n> Main-owner controls only.",
                    reply_markup=admin_menu_kb(),
                )
            except RPCError:
                pass

        elif data == "adm:bots":
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(BotModel).order_by(BotModel.created_at.desc()).limit(20)
                )
                bots = result.scalars().all()
            if not bots:
                try:
                    await cq.message.edit_text("No bots yet.", reply_markup=InlineKeyboardMarkup([[btn(DANGER, "Back", "adm:home")]]))
                except RPCError:
                    pass
                return
            lines = ["**All Bots** (latest 20)\n"]
            for b in bots:
                lines.append(f"→ @{b.bot_username or b.id} — owner {b.owner_id}")
            try:
                await cq.message.edit_text(
                    "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup([[btn(DANGER, "Back", "adm:home", icon=EMOJI_OCTAGON)]]),
                )
            except RPCError:
                pass

        elif data == "adm:owners":
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Owner).order_by(Owner.created_at.desc()).limit(20)
                )
                owners = result.scalars().all()
            lines = ["**All Owners** (latest 20)\n"]
            for o in owners:
                handle = f"@{o.username}" if o.username else f"id:{o.telegram_id}"
                lines.append(f"• {o.first_name or 'Unknown'} {handle}")
            try:
                await cq.message.edit_text(
                    "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup([[btn(DANGER, "Back", "adm:home", icon=EMOJI_OCTAGON)]]),
                )
            except RPCError:
                pass

        elif data == "adm:topbots":
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(BotModel.bot_username, func.count(CloneUser.id).label("cnt"))
                    .outerjoin(CloneUser, CloneUser.bot_id == BotModel.id)
                    .group_by(BotModel.id)
                    .order_by(func.count(CloneUser.id).desc())
                    .limit(10)
                )
                rows = result.all()
            lines = ["**Top Bots by Users**\n"]
            for i, (uname, cnt) in enumerate(rows, 1):
                lines.append(f"{i}. @{uname or '?'} — {cnt} users")
            try:
                await cq.message.edit_text(
                    "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup([[btn(DANGER, "Back", "adm:home", icon=EMOJI_OCTAGON)]]),
                )
            except RPCError:
                pass

        elif data == "adm:logs":
            async with AsyncSessionLocal() as session:
                from database.models import OwnerLog
                result = await session.execute(
                    select(OwnerLog).order_by(OwnerLog.time.desc()).limit(15)
                )
                logs_list = result.scalars().all()
            lines = ["**Recent Owner Actions**\n"]
            for entry in logs_list:
                lines.append(f"• Bot {entry.bot_id}: {entry.action[:60]}")
            try:
                await cq.message.edit_text(
                    "\n".join(lines) if len(lines) > 1 else "No logs yet.",
                    reply_markup=InlineKeyboardMarkup([[btn(DANGER, "Back", "adm:home", icon=EMOJI_OCTAGON)]]),
                )
            except RPCError:
                pass

        elif data == "adm:broadcast":
            try:
                await cq.message.edit_text(
                    "📣 **Broadcast — Choose Target**\n\n"
                    "Who should receive this message?",
                    reply_markup=InlineKeyboardMarkup([
                        [btn(PRIMARY, "📡 All Bot Users",     "adm:bc_target:all_users", icon=EMOJI_GLOBE)],
                        [btn(YELLOW,  "👑 Bot Owners Only",   "adm:bc_target:owners",    icon=EMOJI_CROWN)],
                        [btn(DANGER,  "🔙 Cancel",             "adm:home",                icon=EMOJI_OCTAGON)],
                    ]),
                )
            except RPCError:
                pass

        elif data.startswith("adm:bc_target:"):
            target = data.split(":")[2]
            label = "all users across all bots" if target == "all_users" else "all bot owners"
            main_pending[user_id] = PendingAction("await_admin_broadcast", {"target": target})
            try:
                await cq.message.edit_text(
                    f"{TXT_INFO} 📣 Send the message to broadcast to **{label}**.",
                    reply_markup=InlineKeyboardMarkup([[btn(DANGER, "🔙 Cancel", "adm:home", icon=EMOJI_OCTAGON)]]),
                )
            except RPCError:
                pass

    async def _handle_main_fsub_add(client: Client, message: Message) -> None:
        from pyrogram.errors import UsernameNotOccupied, PeerIdInvalid
        from pyrogram.enums import ChatType

        chat = None
        if message.forward_from_chat:
            chat = message.forward_from_chat
        elif message.text:
            username = message.text.strip().lstrip("@")
            try:
                chat = await client.get_chat(username)
            except (UsernameNotOccupied, PeerIdInvalid, RPCError):
                await message.reply_text(f"{TXT_ERR} Couldn't find that channel. Check the @username and try again.")
                return

        if chat is None:
            await message.reply_text(f"{TXT_ERR} Please forward a message from the channel or send its @username.")
            return

        try:
            member = await client.get_chat_member(chat.id, "me")
        except RPCError:
            await message.reply_text(f"{TXT_ERR} The main bot must be an **admin** of that channel first.")
            return
        if member.status.name not in ("ADMINISTRATOR", "OWNER"):
            await message.reply_text(f"{TXT_ERR} The main bot must be an **admin** of that channel first.")
            return

        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(MainBotChannel).where(MainBotChannel.chat_id == chat.id)
            )
            if existing.scalar_one_or_none():
                await message.reply_text(f"{TXT_WARN} That channel is already in the list.")
                main_pending.pop(message.from_user.id, None)
                return
            session.add(MainBotChannel(
                chat_id=chat.id,
                username=getattr(chat, "username", None),
                title=getattr(chat, "title", None),
            ))
            await session.commit()

        main_pending.pop(message.from_user.id, None)
        await message.reply_text(
            f"✅ **{getattr(chat, 'title', chat.id)}** added to main-bot FSub channels.\n\n"
            "New users must join before they can use the bot.",
            reply_markup=InlineKeyboardMarkup([[btn(DANGER, "Back to FSub", "adm:fsub", icon=EMOJI_OCTAGON)]]),
        )

    async def _copy_admin_broadcast(clone: Client, uid: int, message: Message, media_path: str | None) -> None:
        caption = message.caption or None
        if media_path is None:
            await clone.send_message(uid, message.text or "")
            return
        if message.photo:
            await clone.send_photo(uid, media_path, caption=caption)
        elif message.video:
            await clone.send_video(uid, media_path, caption=caption)
        elif message.animation:
            await clone.send_animation(uid, media_path, caption=caption)
        elif message.audio:
            await clone.send_audio(uid, media_path, caption=caption)
        elif message.voice:
            await clone.send_voice(uid, media_path, caption=caption)
        elif message.sticker:
            await clone.send_sticker(uid, media_path)
        else:
            await clone.send_document(uid, media_path, caption=caption)

    async def _handle_admin_broadcast(client: Client, message: Message) -> None:
        pending = main_pending.pop(message.from_user.id, None)
        target = (pending.data or {}).get("target", "all_users") if pending else "all_users"

        if target == "owners":
            await _handle_owners_broadcast(client, message)
            return

        # ── All bot users broadcast ───────────────────────────────────────────
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(CloneUser.bot_id, CloneUser.user_id))
            rows = result.all()

        from collections import defaultdict
        users_by_bot: dict[int, list[int]] = defaultdict(list)
        for b_id, uid in rows:
            users_by_bot[b_id].append(uid)

        total = sum(len(v) for v in users_by_bot.values())
        if total == 0:
            await message.reply_text(f"{TXT_WARN} No users found across any bot yet.")
            return

        progress = await message.reply_text(
            f"📣 Broadcasting to {total} users across {len(users_by_bot)} bot(s)…\n\n░░░░░░░░░░"
        )

        media_path: str | None = None
        if message.media:
            try:
                media_path = await message.download()
            except RPCError:
                media_path = None

        from pyrogram.errors import UserIsBlocked
        success = failed = blocked = offline = 0
        bots_reached = 0
        done = 0

        for b_id, user_ids in users_by_bot.items():
            clone = manager.get(b_id)
            if clone is None:
                offline += len(user_ids)
                done += len(user_ids)
                continue
            bots_reached += 1

            for uid in user_ids:
                try:
                    await _copy_admin_broadcast(clone, uid, message, media_path)
                    success += 1
                except UserIsBlocked:
                    blocked += 1
                except RPCError:
                    failed += 1

                done += 1
                if done % max(1, total // 10) == 0 or done == total:
                    filled = int((done / total) * 10)
                    bar = "█" * filled + "░" * (10 - filled)
                    try:
                        await progress.edit_text(f"📣 Broadcasting…\n\n{bar}\n{done}/{total}")
                    except RPCError:
                        pass

        if media_path:
            import contextlib
            import os
            with contextlib.suppress(OSError):
                os.remove(media_path)

        await progress.edit_text(
            f"✅ **Broadcast Complete**\n\n"
            f"📡 Bots reached: **{bots_reached}/{len(users_by_bot)}**\n"
            f"✔️ Success: **{success}**\n"
            f"❌ Failed: **{failed}**\n"
            f"🚫 Blocked: **{blocked}**\n"
            f"⏸️ Skipped (bot offline): **{offline}**"
        )
        await _log_main(
            client,
            f"📣 **Superadmin Broadcast Finished** (All Users)\n"
            f"Bots reached: {bots_reached}/{len(users_by_bot)}\n"
            f"✔️ {success}  ❌ {failed}  🚫 {blocked}  ⏸️ {offline}",
        )

    async def _handle_owners_broadcast(client: Client, message: Message) -> None:
        """Broadcast via the main bot directly to all registered bot owners."""
        from pyrogram.errors import UserIsBlocked

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Owner.telegram_id))
            owner_ids = [row[0] for row in result.all()]

        total = len(owner_ids)
        if total == 0:
            await message.reply_text(f"{TXT_WARN} No bot owners registered yet.")
            return

        progress = await message.reply_text(
            f"👑 Broadcasting to {total} owner(s)…\n\n░░░░░░░░░░"
        )

        media_path: str | None = None
        if message.media:
            try:
                media_path = await message.download()
            except RPCError:
                media_path = None

        success = failed = blocked = 0
        for i, uid in enumerate(owner_ids, 1):
            try:
                await _copy_admin_broadcast(client, uid, message, media_path)
                success += 1
            except UserIsBlocked:
                blocked += 1
            except RPCError:
                failed += 1

            if i % max(1, total // 10) == 0 or i == total:
                filled = int((i / total) * 10)
                bar = "█" * filled + "░" * (10 - filled)
                try:
                    await progress.edit_text(f"👑 Broadcasting to owners…\n\n{bar}\n{i}/{total}")
                except RPCError:
                    pass

        if media_path:
            import contextlib
            import os
            with contextlib.suppress(OSError):
                os.remove(media_path)

        await progress.edit_text(
            f"✅ **Owners Broadcast Complete**\n\n"
            f"👑 Total owners: **{total}**\n"
            f"✔️ Success: **{success}**\n"
            f"❌ Failed: **{failed}**\n"
            f"🚫 Blocked: **{blocked}**"
        )
        await _log_main(
            client,
            f"📣 **Superadmin Broadcast Finished** (Owners Only)\n"
            f"Owners targeted: {total}\n"
            f"✔️ {success}  ❌ {failed}  🚫 {blocked}",
        )
