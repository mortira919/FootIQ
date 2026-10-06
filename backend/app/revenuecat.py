"""REST API RevenueCat v1 (https://www.revenuecat.com/docs/api-v1/customers).

app_user_id в RevenueCat = Me.id: клиент логинится в SDK с этим id.
- GET /subscribers/{app_user_id}: CustomerInfo, из него берём активный entitlement PRO.
- DELETE /subscribers/{app_user_id}: «Permanently deletes a customer. Deletion is queued asynchronously.»

Подписка при удалении остаётся в App Store / Google Play. «Восстановить покупки» после нового входа заново
привязывает чек к новому app_user_id: при настройке проекта Restore Behavior = «Transfer to new App User ID»
(значение по умолчанию) покупка переносится, и PRO возвращается.
"""

import logging
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

log = logging.getLogger("footiq.revenuecat")


def base_url() -> str:
    return os.environ.get("REVENUECAT_API_URL", "https://api.revenuecat.com/v1").rstrip("/")


def configured() -> bool:
    return bool(os.environ.get("REVENUECAT_SECRET_KEY"))


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['REVENUECAT_SECRET_KEY']}", "Accept": "application/json"}


def _url(app_user_id: str) -> str:
    return f"{base_url()}/subscribers/{quote(app_user_id, safe='')}"


def delete_subscriber(app_user_id: str) -> bool:
    if not configured():
        log.error("RevenueCat: подписчик %s не удалён, нет REVENUECAT_SECRET_KEY", app_user_id)
        return False
    try:
        response = httpx.delete(_url(app_user_id), headers=_headers(), timeout=10)
        # 404: подписчика нет (игрок ничего не покупал), для нас это тоже удалён.
        if response.status_code != 404:
            response.raise_for_status()
        return True
    except httpx.HTTPError:
        log.exception("RevenueCat: удаление подписчика %s не прошло", app_user_id)
        return False


def get_subscriber(app_user_id: str) -> dict | None:
    if not configured():
        return None
    try:
        response = httpx.get(_url(app_user_id), headers=_headers(), timeout=10)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        log.exception("RevenueCat: не удалось получить подписчика %s", app_user_id)
        return None


LIFETIME = "9999-12-31"  # бессрочная покупка: expires_date = null


def entitlement() -> str:
    return os.environ.get("REVENUECAT_ENTITLEMENT", "pro")


def pro_until(subscriber: dict) -> str | None:
    """Дата (ISO, UTC), до которой действует PRO по ответу GET /subscribers, или None, если PRO нет.

    expires_date = null у бессрочной покупки. Во время grace period после проблемы с оплатой доступ сохраняется
    до grace_period_expires_date.
    """
    info = ((subscriber.get("subscriber") or {}).get("entitlements") or {}).get(entitlement())
    if not info:
        return None
    if info.get("expires_date") is None:
        return LIFETIME
    now = datetime.now(timezone.utc)
    ends = [info.get("expires_date"), info.get("grace_period_expires_date")]
    moments = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in ends if value]
    latest = max(moments)
    return latest.date().isoformat() if latest > now else None

