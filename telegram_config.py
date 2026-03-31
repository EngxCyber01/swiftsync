"""Centralized Telegram configuration and secret-safe helpers."""

import os
import re
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    target_id: str

    @property
    def api_url(self) -> str:
        if not self.bot_token:
            return ""
        return f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.target_id)


_TOKEN_PATTERN = re.compile(r"\d{8,11}:[A-Za-z0-9_-]{20,80}")


def redact_secrets(value: str) -> str:
    if not value:
        return ""
    return _TOKEN_PATTERN.sub("[REDACTED_TELEGRAM_TOKEN]", str(value))


def get_telegram_settings() -> TelegramSettings:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    target_id = (
        (os.getenv("TELEGRAM_GROUP_ID") or "").strip()
        or (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        or (os.getenv("TELEGRAM_TARGET_ID") or "").strip()
        or (os.getenv("TELEGRAM_CHANNEL_ID") or "").strip()
        or (os.getenv("TELEGRAM_GROUP_CHAT_ID") or "").strip()
    )
    return TelegramSettings(bot_token=token, target_id=target_id)


def telegram_status() -> dict:
    settings = get_telegram_settings()
    return {
        "bot_token_set": bool(settings.bot_token),
        "target_id_set": bool(settings.target_id),
    }
