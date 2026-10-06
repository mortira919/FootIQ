"""Удаление аккаунта: одно для DELETE /v1/me и для удаления через веб (Apple 5.1.1(v), Google Account deletion)."""

import logging

from app import apple, revenuecat
from app.store import delete_user

log = logging.getLogger("footiq.accounts")


def erase_account(row) -> dict:
    """Отзывает вход Apple, удаляет подписчика RevenueCat, стирает данные из базы.

    Внешние вызовы идут первыми, но их сбой удаление не останавливает: игрок должен исчезнуть в любом случае.
    Возвращает, что получилось у внешних сервисов, для журнала и тестов.
    """
    result = {"appleRevoked": None, "revenuecatDeleted": None}
    if row["provider"] == "apple":
        if row["apple_refresh"]:
            result["appleRevoked"] = apple.revoke(row["apple_refresh"])
        else:
            log.error("Apple-аккаунт %s удаляется без revoke: refresh-токен не был сохранён", row["id"])
            result["appleRevoked"] = False
    result["revenuecatDeleted"] = revenuecat.delete_subscriber(row["id"])
    delete_user(row["id"])
    log.info("Аккаунт %s удалён: %s", row["id"], result)
    return result
