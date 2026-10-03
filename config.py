"""Central configuration for Nexora File Store.

All values are configured directly in this file.
"""

from __future__ import annotations


class Settings:
    # my.telegram.org application credentials
    # Required by the MTProto client library (Kurigram)
    api_id: int = 20432885
    api_hash: str = "4fdcfab1c7f5e24ae69f3ce6bb234dec"

    # Nexora File Store main bot token
    bot_token: str = "8719198691:AAFSNAe7Vxs2J7A256yFmvgCX8B-xQIqn00"

       # MongoDB Atlas
    # Replace with your real MongoDB connection string.
    mongo_uri: str = "mongodb+srv://Anujedit:Anujedit@cluster0.7cs2nhd.mongodb.net/?appName=Cluster0"
    mongo_database: str = "nexora"

    # Telegram numeric user ID of the main owner
    main_owner_id: int = 8729304171

    # Platform logging channels
    public_log_channel_id: int = -1004396123873
    main_log_channel_id: int = -1003873749415

    # Manual UPI details
    upi_id: str = "971916880@ybl"
    upi_name: str = "Anuj Kumar"


settings = Settings()
