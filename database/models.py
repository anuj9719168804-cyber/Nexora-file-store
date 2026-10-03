"""MongoDB models for Nexora File Store."""
from __future__ import annotations
import datetime as dt
import secrets

from database.engine import Base, Mapped, mapped_column, relationship, func

class NexoraWallet(Base):
    """Per-Telegram-user Nexora Coins wallet."""
    __tablename__ = 'nexora_wallets'
    id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    balance: Mapped[int] = mapped_column(default=0, server_default='0')
    lifetime_earned: Mapped[int] = mapped_column(default=0, server_default='0')
    lifetime_spent: Mapped[int] = mapped_column(default=0, server_default='0')
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class NexoraWalletTransaction(Base):
    """Immutable wallet ledger entry."""
    __tablename__ = 'nexora_wallet_transactions'
    id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    amount: Mapped[int] = mapped_column()
    balance_after: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column()
    reference: Mapped[str | None] = mapped_column()
    note: Mapped[str | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class NexoraGiftCode(Base):
    """Main-owner issued redeem code for Nexora Coins."""
    __tablename__ = 'nexora_gift_codes'
    id: Mapped[int] = mapped_column()
    code: Mapped[str] = mapped_column()
    coins: Mapped[int] = mapped_column()
    max_uses: Mapped[int] = mapped_column(default=1)
    uses: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[dt.datetime | None] = mapped_column()
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class NexoraGiftRedemption(Base):
    """Idempotent gift-code redemption record."""
    __tablename__ = 'nexora_gift_redemptions'
    id: Mapped[int] = mapped_column()
    gift_code_id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    redeemed_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class NexoraEconomySettings(Base):
    """Singleton platform economy controls managed by the main owner."""
    __tablename__ = 'nexora_economy_settings'
    id: Mapped[int] = mapped_column(default=1)
    referral_reward: Mapped[int] = mapped_column(default=50, server_default='50')
    referred_reward: Mapped[int] = mapped_column(default=25, server_default='25')
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class NexoraReferral(Base):
    """One referral relationship; a referred user can only qualify once."""
    __tablename__ = 'nexora_referrals'
    id: Mapped[int] = mapped_column()
    referrer_user_id: Mapped[int] = mapped_column()
    referred_user_id: Mapped[int] = mapped_column()
    qualified: Mapped[bool] = mapped_column(default=False)
    rewarded_at: Mapped[dt.datetime | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class NexoraPaymentOrder(Base):
    """Manual UPI purchase submitted by a user and reviewed by the main owner."""
    __tablename__ = 'nexora_payment_orders'
    id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    coins: Mapped[int] = mapped_column()
    amount_inr: Mapped[int] = mapped_column()
    utr: Mapped[str | None] = mapped_column()
    status: Mapped[str] = mapped_column(default='pending')
    reviewed_by: Mapped[int | None] = mapped_column()
    reviewed_at: Mapped[dt.datetime | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class Owner(Base):
    __tablename__ = 'owners'
    id: Mapped[int] = mapped_column()
    telegram_id: Mapped[int] = mapped_column()
    username: Mapped[str | None] = mapped_column()
    first_name: Mapped[str | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    bots: Mapped[list['Bot']] = relationship(back_populates='owner', cascade='all, delete-orphan')

class Bot(Base):
    __tablename__ = 'bots'
    id: Mapped[int] = mapped_column()
    owner_id: Mapped[int] = mapped_column()
    bot_token: Mapped[str] = mapped_column()
    bot_username: Mapped[str | None] = mapped_column()
    bot_name: Mapped[str | None] = mapped_column()
    bot_photo: Mapped[str | None] = mapped_column()
    bot_type: Mapped[str] = mapped_column(default='v2', server_default='v2')
    welcome_caption: Mapped[str | None] = mapped_column()
    welcome_image: Mapped[str | None] = mapped_column()
    log_channel: Mapped[int | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    active: Mapped[bool] = mapped_column(default=True)
    owner: Mapped['Owner'] = relationship(back_populates='bots')
    channels: Mapped[list['BotChannel']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    folder_links: Mapped[list['FolderLink']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    files: Mapped[list['UploadedFile']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    users: Mapped[list['CloneUser']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    broadcasts: Mapped[list['Broadcast']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    settings: Mapped['BotSettings'] = relationship(back_populates='bot', uselist=False, cascade='all, delete-orphan')
    protected_links: Mapped[list['ProtectedLink']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    cricket_tours: Mapped[list['CricketTour']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    cricket_players: Mapped[list['CricketPlayer']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    cricket_questions: Mapped[list['CricketQuestion']] = relationship(back_populates='bot', cascade='all, delete-orphan')
    cricket_settings: Mapped['CricketSettings'] = relationship(back_populates='bot', uselist=False, cascade='all, delete-orphan')

class BotChannel(Base):
    __tablename__ = 'bot_channels'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    chat_id: Mapped[int] = mapped_column()
    username: Mapped[str | None] = mapped_column()
    title: Mapped[str | None] = mapped_column()
    type: Mapped[str] = mapped_column(default='channel')
    required: Mapped[bool] = mapped_column(default=True)
    position: Mapped[int] = mapped_column(default=0)
    bot: Mapped['Bot'] = relationship(back_populates='channels')

class FolderLink(Base):
    __tablename__ = 'folder_links'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    invite_link: Mapped[str] = mapped_column()
    bot: Mapped['Bot'] = relationship(back_populates='folder_links')

class UploadedFile(Base):
    __tablename__ = 'uploaded_files'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    file_unique_id: Mapped[str] = mapped_column()
    file_id: Mapped[str] = mapped_column()
    type: Mapped[str] = mapped_column()
    caption: Mapped[str | None] = mapped_column()
    size: Mapped[int | None] = mapped_column()
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    bot: Mapped['Bot'] = relationship(back_populates='files')

class ProtectedLink(Base):
    """A URL protected behind the bot's force-subscribe gate."""
    __tablename__ = 'protected_links'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    token: Mapped[str] = mapped_column(default=lambda: secrets.token_urlsafe(12))
    original_url: Mapped[str] = mapped_column()
    title: Mapped[str | None] = mapped_column()
    click_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    bot: Mapped['Bot'] = relationship(back_populates='protected_links')

class CloneUser(Base):
    __tablename__ = 'clone_users'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    username: Mapped[str | None] = mapped_column()
    name: Mapped[str | None] = mapped_column()
    verified: Mapped[bool] = mapped_column(default=False)
    joined_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    last_seen: Mapped[dt.datetime | None] = mapped_column()
    bot: Mapped['Bot'] = relationship(back_populates='users')

class JoinLog(Base):
    __tablename__ = 'join_logs'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    channel_id: Mapped[int] = mapped_column()
    joined: Mapped[bool] = mapped_column(default=False)
    time: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class Broadcast(Base):
    __tablename__ = 'broadcasts'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    message: Mapped[str | None] = mapped_column()
    started_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[dt.datetime | None] = mapped_column()
    success: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    blocked: Mapped[int] = mapped_column(default=0)
    bot: Mapped['Bot'] = relationship(back_populates='broadcasts')

class BotSettings(Base):
    __tablename__ = 'bot_settings'
    bot_id: Mapped[int] = mapped_column()
    auto_delete: Mapped[int] = mapped_column(default=0)
    protect_content: Mapped[bool] = mapped_column(default=False)
    send_files_once: Mapped[bool] = mapped_column(default=False)
    welcome_enabled: Mapped[bool] = mapped_column(default=True)
    force_subscribe: Mapped[bool] = mapped_column(default=True)
    verify_button: Mapped[bool] = mapped_column(default=True)
    custom_start: Mapped[str | None] = mapped_column()
    custom_photo: Mapped[str | None] = mapped_column()
    bot: Mapped['Bot'] = relationship(back_populates='settings')

class OwnerLog(Base):
    __tablename__ = 'owner_logs'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    action: Mapped[str] = mapped_column()
    time: Mapped[dt.datetime] = mapped_column(server_default=func.now())

class MainBotChannel(Base):
    """Force-subscribe channels required by the main Nexora bot itself."""
    __tablename__ = 'main_bot_channels'
    id: Mapped[int] = mapped_column()
    chat_id: Mapped[int] = mapped_column()
    username: Mapped[str | None] = mapped_column()
    title: Mapped[str | None] = mapped_column()
    required: Mapped[bool] = mapped_column(default=True)

class CricketTour(Base):
    """A tournament created by a cricket bot owner."""
    __tablename__ = 'cricket_tours'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column()
    details: Mapped[str | None] = mapped_column()
    prize_pool: Mapped[str | None] = mapped_column()
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    bot: Mapped['Bot'] = relationship(back_populates='cricket_tours')
    players: Mapped[list['CricketPlayer']] = relationship(back_populates='tour', cascade='all, delete-orphan')

class CricketPlayer(Base):
    """A registered player / captain in a cricket tournament."""
    __tablename__ = 'cricket_players'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    tour_id: Mapped[int | None] = mapped_column()
    user_id: Mapped[int] = mapped_column()
    username: Mapped[str | None] = mapped_column()
    full_name: Mapped[str | None] = mapped_column()
    role: Mapped[str | None] = mapped_column()
    is_captain: Mapped[bool] = mapped_column(default=False)
    base_price: Mapped[str | None] = mapped_column()
    team_name: Mapped[str | None] = mapped_column()
    team_logo: Mapped[str | None] = mapped_column()
    status: Mapped[str] = mapped_column(default='pending')
    answers: Mapped[str | None] = mapped_column()
    registered_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    bot: Mapped['Bot'] = relationship(back_populates='cricket_players')
    tour: Mapped['CricketTour | None'] = relationship(back_populates='players')

class CricketQuestion(Base):
    """Owner-configurable additional registration questions."""
    __tablename__ = 'cricket_questions'
    id: Mapped[int] = mapped_column()
    bot_id: Mapped[int] = mapped_column()
    key: Mapped[str] = mapped_column()
    label: Mapped[str] = mapped_column()
    input_type: Mapped[str] = mapped_column(default='text')
    choices: Mapped[str | None] = mapped_column()
    enabled: Mapped[bool] = mapped_column(default=True)
    required: Mapped[bool] = mapped_column(default=False)
    order_index: Mapped[int] = mapped_column(default=0)
    captain_only: Mapped[bool] = mapped_column(default=False)
    bot: Mapped['Bot'] = relationship(back_populates='cricket_questions')

class CricketSettings(Base):
    """Per-bot cricket settings."""
    __tablename__ = 'cricket_settings'
    bot_id: Mapped[int] = mapped_column()
    auto_approve: Mapped[bool] = mapped_column(default=False)
    allow_captain_reg: Mapped[bool] = mapped_column(default=True)
    max_players: Mapped[int] = mapped_column(default=0)
    max_captains: Mapped[int] = mapped_column(default=0)
    reg_end_date: Mapped[dt.datetime | None] = mapped_column()
    admin_gc: Mapped[int | None] = mapped_column()
    welcome_image_disabled: Mapped[bool] = mapped_column(default=False)
    base_price_options: Mapped[str | None] = mapped_column()
    bot: Mapped['Bot'] = relationship(back_populates='cricket_settings')
