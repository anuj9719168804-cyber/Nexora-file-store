"""Nexora Coins, referral and redemption helpers."""
from __future__ import annotations

import datetime as dt
import secrets
import string

from database.engine import select

from database.models import (
    NexoraEconomySettings,
    NexoraGiftCode,
    NexoraGiftRedemption,
    NexoraReferral,
    NexoraWallet,
    NexoraWalletTransaction,
)


async def get_wallet(session, user_id: int) -> NexoraWallet:
    result = await session.execute(select(NexoraWallet).where(NexoraWallet.user_id == user_id))
    wallet = result.scalar_one_or_none()
    if wallet is None:
        wallet = NexoraWallet(user_id=user_id)
        session.add(wallet)
        await session.flush()
    return wallet


async def credit(
    session,
    user_id: int,
    amount: int,
    *,
    kind: str,
    reference: str | None = None,
    note: str | None = None,
) -> NexoraWallet:
    if amount <= 0:
        raise ValueError("Credit amount must be positive")
    wallet = await get_wallet(session, user_id)
    wallet.balance += amount
    wallet.lifetime_earned += amount
    session.add(
        NexoraWalletTransaction(
            user_id=user_id,
            amount=amount,
            balance_after=wallet.balance,
            kind=kind,
            reference=reference,
            note=note,
        )
    )
    await session.flush()
    return wallet


async def debit(
    session,
    user_id: int,
    amount: int,
    *,
    kind: str,
    reference: str | None = None,
    note: str | None = None,
) -> NexoraWallet:
    if amount <= 0:
        raise ValueError("Debit amount must be positive")
    wallet = await get_wallet(session, user_id)
    if wallet.balance < amount:
        raise ValueError("Insufficient balance")
    wallet.balance -= amount
    wallet.lifetime_spent += amount
    session.add(
        NexoraWalletTransaction(
            user_id=user_id,
            amount=-amount,
            balance_after=wallet.balance,
            kind=kind,
            reference=reference,
            note=note,
        )
    )
    await session.flush()
    return wallet


async def get_economy_settings(session) -> NexoraEconomySettings:
    settings = await session.get(NexoraEconomySettings, 1)
    if settings is None:
        settings = NexoraEconomySettings(id=1)
        session.add(settings)
        await session.flush()
    return settings


def new_gift_code(prefix: str = "NEXORA") -> str:
    alphabet = string.ascii_uppercase + string.digits
    return f"{prefix}-{''.join(secrets.choice(alphabet) for _ in range(10))}"


async def redeem_code(session, user_id: int, code: str) -> tuple[bool, str, int]:
    result = await session.execute(
        select(NexoraGiftCode).where(NexoraGiftCode.code == code.upper().strip()).with_for_update()
    )
    gift = result.scalar_one_or_none()
    if gift is None:
        return False, "That code does not exist.", 0
    if not gift.active:
        return False, "That code is no longer active.", 0
    if gift.expires_at and gift.expires_at <= dt.datetime.now(dt.timezone.utc):
        gift.active = False
        return False, "That code has expired.", 0
    if gift.uses >= gift.max_uses:
        gift.active = False
        return False, "That code has reached its usage limit.", 0

    duplicate = await session.execute(
        select(NexoraGiftRedemption).where(
            NexoraGiftRedemption.gift_code_id == gift.id,
            NexoraGiftRedemption.user_id == user_id,
        )
    )
    if duplicate.scalar_one_or_none() is not None:
        return False, "You have already redeemed that code.", 0

    await credit(
        session,
        user_id,
        gift.coins,
        kind="gift",
        reference=gift.code,
        note="Gift code redemption",
    )
    session.add(NexoraGiftRedemption(gift_code_id=gift.id, user_id=user_id))
    gift.uses += 1
    if gift.uses >= gift.max_uses:
        gift.active = False
    return True, "Gift code redeemed.", gift.coins


async def qualify_referral(session, referred_user_id: int) -> tuple[int, int] | None:
    result = await session.execute(
        select(NexoraReferral).where(
            NexoraReferral.referred_user_id == referred_user_id,
            NexoraReferral.qualified.is_(False),
        ).with_for_update()
    )
    referral = result.scalar_one_or_none()
    if referral is None or referral.referrer_user_id == referred_user_id:
        return None

    settings = await get_economy_settings(session)
    await credit(
        session,
        referral.referrer_user_id,
        settings.referral_reward,
        kind="referral",
        reference=str(referral.id),
        note="Referral reward",
    )
    await credit(
        session,
        referral.referred_user_id,
        settings.referred_reward,
        kind="referral_bonus",
        reference=str(referral.id),
        note="Welcome referral bonus",
    )
    referral.qualified = True
    referral.rewarded_at = dt.datetime.now(dt.timezone.utc)
    return referral.referrer_user_id, settings.referral_reward


async def create_referral(session, referrer_user_id: int, referred_user_id: int) -> bool:
    if referrer_user_id == referred_user_id:
        return False
    existing = await session.execute(
        select(NexoraReferral).where(NexoraReferral.referred_user_id == referred_user_id)
    )
    if existing.scalar_one_or_none() is not None:
        return False
    session.add(
        NexoraReferral(
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_user_id,
        )
    )
    return True
