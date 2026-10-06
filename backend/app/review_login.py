"""Вход по логину и паролю для одного служебного аккаунта ревьюеров App Store и Google Play.

Включается и выключается на сервере:
- REVIEW_LOGIN_ENABLED=true, REVIEW_LOGIN=<логин>, REVIEW_PASSWORD_HASH=<хэш из scripts/review_password.py>;
- без любого из них POST /v1/auth/review отвечает 404, как будто пути нет.

В секретах хранится только хэш пароля: pbkdf2_sha256$<итерации>$<соль hex>$<хэш hex>.
Аккаунт: provider = google, sub = REVIEW_SUB. Настоящий Google sub состоит из цифр, поэтому к этой строке
не привяжется ни один вход через Google: аккаунт отвязан от Gmail.
"""

import hashlib
import hmac
import os
import secrets

REVIEW_SUB = "review-login"
ITERATIONS = 600_000


def enabled() -> bool:
    return (
        os.environ.get("REVIEW_LOGIN_ENABLED", "").lower() in ("1", "true", "yes")
        and bool(os.environ.get("REVIEW_LOGIN"))
        and bool(os.environ.get("REVIEW_PASSWORD_HASH"))
    )


def make_hash(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def password_ok(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def credentials_ok(login: str, password: str) -> bool:
    # Оба сравнения выполняются всегда, чтобы время ответа не выдавало, совпал ли логин.
    login_ok = hmac.compare_digest(login.strip().encode(), os.environ["REVIEW_LOGIN"].encode())
    return password_ok(password, os.environ["REVIEW_PASSWORD_HASH"]) and login_ok


def email() -> str:
    return os.environ.get("REVIEW_EMAIL", "review@amplua.app")
