"""SQLAlchemy models for Nexora File Store (Neon Postgres)."""
from __future__ import annotations
from database.engine import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

class Base(DeclarativeBase):
    pass


class NexoraWallet(Base):
    """Per-Telegram-user Nexora Coins wallet."""
    __tablename__ = "nexora_wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lifetime_earned: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lifetime_spent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NexoraWalletTransaction(Base):
    """Immutable wallet ledger entry."""
    __tablename__ = "nexora_wallet_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NexoraGiftCode(Base):
    """Main-owner issued redeem code for Nexora Coins."""
    __tablename__ = "nexora_gift_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    coins: Mapped[int] = mapped_column(Integer)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NexoraGiftRedemption(Base):
    """Idempotent gift-code redemption record."""
    __tablename__ = "nexora_gift_redemptions"
    __table_args__ = (UniqueConstraint("gift_code_id", "user_id", name="uq_gift_redemption"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gift_code_id: Mapped[int] = mapped_column(ForeignKey("nexora_gift_codes.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    redeemed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NexoraEconomySettings(Base):
    """Singleton platform economy controls managed by the main owner."""
    __tablename__ = "nexora_economy_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    referral_reward: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    referred_reward: Mapped[int] = mapped_column(Integer, default=25, server_default="25")
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NexoraReferral(Base):
    """One referral relationship; a referred user can only qualify once."""
    __tablename__ = "nexora_referrals"
    __table_args__ = (UniqueConstraint("referred_user_id", name="uq_nexora_referred_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    referred_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    qualified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rewarded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NexoraPaymentOrder(Base):
    """Manual UPI purchase submitted by a user and reviewed by the main owner."""
    __tablename__ = "nexora_payment_orders"
    __table_args__ = (UniqueConstraint("utr", name="uq_nexora_payment_utr"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    coins: Mapped[int] = mapped_column(Integer)
    amount_inr: Mapped[int] = mapped_column(Integer)
    utr: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bots: Mapped[list["Bot"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id", ondelete="CASCADE"))
    bot_token: Mapped[str] = mapped_column(Text, unique=True)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bot_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bot_photo: Mapped[str | None] = mapped_column(Text, nullable=True)
    bot_type: Mapped[str] = mapped_column(String(32), default="v2", server_default="v2")
    welcome_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_channel: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    owner: Mapped["Owner"] = relationship(back_populates="bots")
    channels: Mapped[list["BotChannel"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    folder_links: Mapped[list["FolderLink"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    files: Mapped[list["UploadedFile"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    users: Mapped[list["CloneUser"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    broadcasts: Mapped[list["Broadcast"]] = relationship(back_populates="bot", cascade="all, delete-orphan")
    settings: Mapped["BotSettings"] = relationship(
        back_populates="bot", uselist=False, cascade="all, delete-orphan"
    )
    protected_links: Mapped[list["ProtectedLink"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    # Cricket
    cricket_tours: Mapped[list["CricketTour"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    cricket_players: Mapped[list["CricketPlayer"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    cricket_questions: Mapped[list["CricketQuestion"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    cricket_settings: Mapped["CricketSettings"] = relationship(
        back_populates="bot", uselist=False, cascade="all, delete-orphan"
    )


class BotChannel(Base):
    __tablename__ = "bot_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    type: Mapped[str] = mapped_column(String(32), default="channel")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    bot: Mapped["Bot"] = relationship(back_populates="channels")


class FolderLink(Base):
    __tablename__ = "folder_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    invite_link: Mapped[str] = mapped_column(Text)

    bot: Mapped["Bot"] = relationship(back_populates="folder_links")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    file_unique_id: Mapped[str] = mapped_column(String(128))
    file_id: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(32))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bot: Mapped["Bot"] = relationship(back_populates="files")


class ProtectedLink(Base):
    """A URL protected behind the bot's force-subscribe gate."""
    __tablename__ = "protected_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True, default=lambda: secrets.token_urlsafe(12))
    original_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    click_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bot: Mapped["Bot"] = relationship(back_populates="protected_links")


class CloneUser(Base):
    __tablename__ = "clone_users"
    __table_args__ = (UniqueConstraint("bot_id", "user_id", name="uq_clone_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bot: Mapped["Bot"] = relationship(back_populates="users")


class JoinLog(Base):
    __tablename__ = "join_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    joined: Mapped[bool] = mapped_column(Boolean, default=False)
    time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    success: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[int] = mapped_column(Integer, default=0)

    bot: Mapped["Bot"] = relationship(back_populates="broadcasts")


class BotSettings(Base):
    __tablename__ = "bot_settings"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True)
    auto_delete: Mapped[int] = mapped_column(Integer, default=0)
    protect_content: Mapped[bool] = mapped_column(Boolean, default=False)
    send_files_once: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    force_subscribe: Mapped[bool] = mapped_column(Boolean, default=True)
    verify_button: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_start: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_photo: Mapped[str | None] = mapped_column(Text, nullable=True)

    bot: Mapped["Bot"] = relationship(back_populates="settings")


class OwnerLog(Base):
    __tablename__ = "owner_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(Text)
    time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MainBotChannel(Base):
    """Force-subscribe channels required by the main Nexora bot itself."""
    __tablename__ = "main_bot_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)


# ── Cricket Tournament Models ─────────────────────────────────────────────────

class CricketTour(Base):
    """A tournament created by a cricket bot owner."""
    __tablename__ = "cricket_tours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    prize_pool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bot: Mapped["Bot"] = relationship(back_populates="cricket_tours")
    players: Mapped[list["CricketPlayer"]] = relationship(
        back_populates="tour", cascade="all, delete-orphan"
    )


class CricketPlayer(Base):
    """A registered player / captain in a cricket tournament."""
    __tablename__ = "cricket_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    tour_id: Mapped[int | None] = mapped_column(ForeignKey("cricket_tours.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_captain: Mapped[bool] = mapped_column(Boolean, default=False)
    base_price: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Captain-specific fields
    team_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    team_logo: Mapped[str | None] = mapped_column(Text, nullable=True)
    # status: pending | approved | rejected | waitlisted | deregistered
    status: Mapped[str] = mapped_column(String(16), default="pending")
    answers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    registered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bot: Mapped["Bot"] = relationship(back_populates="cricket_players")
    tour: Mapped["CricketTour | None"] = relationship(back_populates="players")


class CricketQuestion(Base):
    """Owner-configurable additional registration questions."""
    __tablename__ = "cricket_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(256))
    # input_type: text | choice | number
    input_type: Mapped[str] = mapped_column(String(16), default="text")
    choices: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # If True, this question is only shown to captains (not regular players)
    captain_only: Mapped[bool] = mapped_column(Boolean, default=False)

    bot: Mapped["Bot"] = relationship(back_populates="cricket_questions")


class CricketSettings(Base):
    """Per-bot cricket settings."""
    __tablename__ = "cricket_settings"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_captain_reg: Mapped[bool] = mapped_column(Boolean, default=True)
    max_players: Mapped[int] = mapped_column(Integer, default=0)   # 0 = unlimited
    max_captains: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    reg_end_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Admin group chat — registration notifications are forwarded here
    admin_gc: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Welcome/start image control
    welcome_image_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Owner-configured base price options shown to players during registration.
    # Stored as a JSON array of ints, e.g. "[10, 50, 100]". These are CREDITS, not currency.
    base_price_options: Mapped[str | None] = mapped_column(Text, nullable=True)

    bot: Mapped["Bot"] = relationship(back_populates="cricket_settings")
