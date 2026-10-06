"""Sign in with Apple на сервере: обмен authorizationCode на refresh-токен и отзыв токена при удалении аккаунта.

Документация Apple:
- https://developer.apple.com/documentation/sign_in_with_apple/generate_and_validate_tokens
- https://developer.apple.com/documentation/sign_in_with_apple/revoke_tokens

client_secret это JWT ES256, подписанный ключом Sign in with Apple (.p8): iss = Team ID, sub = bundle id
(client_id), aud = https://appleid.apple.com, kid = Key ID. Живёт не дольше 6 месяцев, мы выпускаем на 5 минут.
"""

import logging
import os
import time

import httpx
import jwt

log = logging.getLogger("footiq.apple")

AUDIENCE = "https://appleid.apple.com"
SECRET_TTL = 300


def base_url() -> str:
    # В тестах сюда подставляется адрес локального мок-сервера.
    return os.environ.get("APPLE_AUTH_URL", "https://appleid.apple.com").rstrip("/")


def configured() -> bool:
    return all(os.environ.get(name) for name in ("APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY", "APPLE_BUNDLE_ID"))


def client_id() -> str:
    # APPLE_BUNDLE_ID может содержать несколько aud через запятую (приложение и Services ID); для токенов нужен первый.
    return os.environ["APPLE_BUNDLE_ID"].split(",")[0].strip()


def client_secret() -> str:
    now = int(time.time())
    claims = {"iss": os.environ["APPLE_TEAM_ID"], "iat": now, "exp": now + SECRET_TTL, "aud": AUDIENCE, "sub": client_id()}
    key = os.environ["APPLE_PRIVATE_KEY"].replace("\\n", "\n")
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": os.environ["APPLE_KEY_ID"]})


def _post(path: str, data: dict) -> httpx.Response:
    payload = {"client_id": client_id(), "client_secret": client_secret(), **data}
    return httpx.post(f"{base_url()}/auth/{path}", data=payload, timeout=10)


def exchange_code(code: str) -> str | None:
    """authorizationCode → refresh_token. None, если ключ не настроен или Apple отказал."""
    if not configured():
        log.error("Apple refresh-токен не сохранён: нет APPLE_TEAM_ID / APPLE_KEY_ID / APPLE_PRIVATE_KEY, отозвать вход при удалении будет нечем")
        return None
    try:
        response = _post("token", {"code": code, "grant_type": "authorization_code"})
        response.raise_for_status()
        return response.json().get("refresh_token")
    except (httpx.HTTPError, ValueError):
        log.exception("Apple /auth/token не прошёл")
        return None


def revoke(refresh_token: str) -> bool:
    """Отзывает refresh-токен. False, если не получилось: удаление аккаунта при этом не останавливается."""
    if not configured():
        log.error("Apple revoke пропущен: нет ключа Sign in with Apple")
        return False
    try:
        response = _post("revoke", {"token": refresh_token, "token_type_hint": "refresh_token"})
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        log.exception("Apple /auth/revoke не прошёл")
        return False
