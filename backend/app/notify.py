"""Уведомление модераторов о новой жалобе в Telegram, чтобы отреагировать в течение 24 часов (Apple 1.2).

Нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID. Без них жалоба только пишется в журнал сервера,
а очередь по-прежнему видна в /admin.
"""

import logging
import os

import httpx

log = logging.getLogger("footiq.notify")


def base_url() -> str:
    return os.environ.get("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")


def send(text: str) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        log.warning("Уведомление модераторам не отправлено (нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID): %s", text)
        return False
    try:
        response = httpx.post(
            f"{base_url()}/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        log.exception("Telegram: уведомление не отправлено")
        return False
