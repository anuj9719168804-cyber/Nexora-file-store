"""Central configuration for Nexora File Store.

All values come from environment variables / secrets — never hardcode
credentials in source. See replit.md for the required variable names.
"""
from __future__ import annotations

import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Set it via Replit secrets before starting the bot."
        )
    return value


class Settings:
    # my.telegram.org application credentials — required by the MTProto
    # client library (Kurigram) for every bot, including the main bot and
    # every clone.
    api_id: int = int(_require("TELEGRAM_API_ID", "20432885"))
    api_hash: str = _require("TELEGRAM_API_HASH", "4fdcfab1c7f5e24ae69f3ce6bb234dec")

    # Nexora File Store main bot token (from @BotFather).
    bot_token: str = _require("TELEGRAM_BOT_TOKEN", "8719198691:AAFSNAe7Vxs2J7A256yFmvgCX8B-xQIqn00")

    # Neon Postgres connection string, e.g.
    # postgresql://user:pass@host/db?sslmode=require
    database_url: str = _require("NEON_DATABASE_URL", "")

    # Telegram numeric user id of the person who administers Nexora itself.
    # Defaults to the known owner ID; can be overridden via env var.
    main_owner_id: int = int(os.environ.get("MAIN_BOT_OWNER_ID", "8729304171"))

    # Platform logging channels. Environment variables can override these defaults.
    public_log_channel_id: int = int(os.environ.get("PUBLIC_LOG_CHANNEL_ID", "-1004396123873"))
    main_log_channel_id: int = int(os.environ.get("MAIN_LOG_CHANNEL_ID", "-1003873749415"))

    # Manual UPI details shown in the Balance -> Add Balance flow.
    upi_id: str = os.environ.get("NEXORA_UPI_ID", "971916880@ybl")
    upi_name: str = os.environ.get("NEXORA_UPI_NAME", "Anuj Kumar")


settings = Settings()
