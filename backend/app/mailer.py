"""Отправка писем через SMTP (письмо со ссылкой на удаление аккаунта).

Настройки в секретах сервера: SMTP_HOST, SMTP_PORT (465 = SSL, иначе STARTTLS), SMTP_USER, SMTP_PASSWORD, MAIL_FROM.
Подойдёт любой SMTP: Gmail с паролем приложения, Яндекс, почта на домене.
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Callable

log = logging.getLogger("footiq.mailer")


def configured() -> bool:
    return all(os.environ.get(name) for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM"))


def _smtp_send(message: EmailMessage) -> None:
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465"))
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as smtp:
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls(context=context)
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(message)


# Точка подмены для тестов: функция (EmailMessage) -> None.
deliver: Callable[[EmailMessage], None] = _smtp_send


def send(to: str, subject: str, text: str) -> bool:
    message = EmailMessage()
    message["From"] = os.environ.get("MAIL_FROM", "Amplua <no-reply@amplua.app>")
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if deliver is _smtp_send and not configured():
        log.error("Письмо «%s» не отправлено: SMTP не настроен", subject)
        return False
    try:
        deliver(message)
        return True
    except (OSError, smtplib.SMTPException):
        log.exception("Письмо «%s» не отправлено", subject)
        return False
