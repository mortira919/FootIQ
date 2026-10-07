"""Удаление аккаунта через веб (Google Play «Account deletion»: ссылка в форме Data safety).

Работает и тогда, когда приложения на телефоне уже нет:
1. GET /delete-account: форма с email и описанием, что удаляется и в какой срок.
2. POST /delete-account: всегда один и тот же нейтральный ответ. Если email принадлежит аккаунту, на него уходит
   письмо со ссылкой. По ответу нельзя узнать, есть ли такой аккаунт.
3. GET /delete-account/confirm?token=…: страница с кнопкой «Удалить навсегда». Сама ссылка ничего не удаляет,
   чтобы превью ссылок в почтовиках и антивирусы не стирали аккаунты.
4. POST /delete-account/confirm: то же удаление, что DELETE /v1/me (app/accounts.py).

Токен: 32 случайных байта, в базе только SHA-256, ссылка живёт 24 часа и одноразовая.
"""

import hashlib
import html
import os
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app import mailer
from app.accounts import erase_account
from app.store import DELETION_TTL_HOURS, add_deletion_request, deletion_user, user_row, users_by_email

SITE = Path(__file__).resolve().parent / "site"
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
SENT = "Если аккаунт Amplua с этим адресом существует, мы отправили на него письмо со ссылкой. Ссылка действует 24 часа."
router = APIRouter()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public_url(request: Request) -> str:
    return os.environ.get("PUBLIC_URL", str(request.base_url)).rstrip("/")


def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    support = html.escape(os.environ.get("SUPPORT_EMAIL", "support@amplua.app"))
    return HTMLResponse(
        f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)} · Amplua</title>
<link rel="icon" href="/assets/mark.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/site.css">
</head>
<body>
<header class="top"><a class="brand" href="/"><img src="/assets/mark.svg" alt="" width="32" height="32">Amplua</a></header>
<main class="doc">
  <h1>{html.escape(title)}</h1>
  {body}
</main>
<footer class="foot"><div class="inner"><span>© 2026 Команда Amplua</span>
<nav aria-label="Документы"><a href="/privacy">Политика конфиденциальности</a><a href="/terms">Условия использования</a><a href="mailto:{support}">{support}</a></nav></div></footer>
</body>
</html>""",
        status_code=status,
    )


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body())[:4096].decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(raw).items()}


def _limit(key: str, per_minute: int) -> bool:
    from app.main import _hit  # общий ограничитель частоты сервера

    try:
        _hit(key, per_minute)
        return True
    except HTTPException:
        return False


@router.get("/delete-account", include_in_schema=False)
def form_page() -> FileResponse:
    return FileResponse(SITE / "delete-account.html")


@router.get("/delete", include_in_schema=False)
def old_address() -> RedirectResponse:
    return RedirectResponse("/delete-account", status_code=308)


def _send_links(email: str, base: str) -> None:
    for row in users_by_email(email):
        token = secrets.token_urlsafe(32)
        add_deletion_request(_hash(token), row["id"])
        link = f"{base}/delete-account/confirm?token={token}"
        mailer.send(
            email,
            "Удаление аккаунта Amplua",
            "Кто-то, возможно ты, запросил удаление аккаунта Amplua, привязанного к этому адресу.\n\n"
            f"Чтобы удалить аккаунт и все данные, открой ссылку и подтверди удаление:\n{link}\n\n"
            f"Ссылка действует {DELETION_TTL_HOURS} часа. Если ты ничего не запрашивал, просто удали это письмо: аккаунт останется.\n\n"
            "Подписку PRO удаление не отменяет: отмени её в настройках подписок App Store или Google Play.",
        )


@router.post("/delete-account", include_in_schema=False)
async def request_deletion(request: Request, background: BackgroundTasks) -> HTMLResponse:
    host = request.client.host if request.client else "unknown"
    email = (await _form(request)).get("email", "").strip()
    if not EMAIL.fullmatch(email):
        return page("Удаление аккаунта", '<p>Проверь адрес почты и попробуй ещё раз. <a href="/delete-account">Назад к форме</a></p>', 400)
    if not (_limit("webdel-ip:" + host, 5) and _limit("webdel-mail:" + email.lower(), 2)):
        return page("Удаление аккаунта", "<p>Слишком много запросов. Попробуй через минуту.</p>", 429)
    # Письмо уходит в фоне: время ответа не зависит от того, есть ли аккаунт.
    background.add_task(_send_links, email, _public_url(request))
    return page("Проверь почту", f"<p>{html.escape(SENT)}</p><p>Письма нет? Проверь папку «Спам». Если ты входил через Apple со скрытым адресом, письмо придёт через переадресацию Apple на твою настоящую почту.</p>")


@router.get("/delete-account/confirm", include_in_schema=False)
def confirm_page(token: str = "") -> HTMLResponse:
    user_id = deletion_user(_hash(token)) if token else None
    if user_id is None:
        return page("Ссылка недействительна", '<p>Ссылка устарела или уже использована. <a href="/delete-account">Запросить новую</a></p>', 410)
    return page(
        "Удалить аккаунт навсегда?",
        "<p>Удалятся профиль, рейтинг, история решений, ответы в Раздевалке, лиги, которые ты создал, и все остальные данные. "
        "Восстановить аккаунт будет нельзя. Подписку PRO удаление не отменяет.</p>"
        '<form method="post" action="/delete-account/confirm" class="box">'
        f'<input type="hidden" name="token" value="{html.escape(token)}">'
        '<button class="btn" type="submit">Удалить навсегда</button></form>',
    )


@router.post("/delete-account/confirm", include_in_schema=False)
async def confirm(request: Request) -> HTMLResponse:
    token = (await _form(request)).get("token", "")
    user_id = deletion_user(_hash(token)) if token else None
    row = user_row(user_id) if user_id else None
    if row is None:
        return page("Ссылка недействительна", '<p>Ссылка устарела или уже использована. <a href="/delete-account">Запросить новую</a></p>', 410)
    erase_account(row)
    return page("Аккаунт удалён", "<p>Аккаунт и все данные удалены. Если войдёшь снова, начнёшь с нуля.</p>")
