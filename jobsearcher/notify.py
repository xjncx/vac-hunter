from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any


class NotifyError(RuntimeError):
    pass


def send_vacancy_digest(config: dict[str, Any], vacancies: list[dict[str, Any]]) -> None:
    recipient = str(config.get("notification_email") or "").strip()
    username = str(config.get("mail_username") or "").strip()
    password = str(config.get("mail_password") or "")
    if not recipient or not vacancies:
        return
    if not username or not password:
        raise NotifyError("Для отправки уведомлений нужны mail_username и mail_password")

    smtp_host = str(config.get("smtp_host") or "smtp.gmail.com")
    smtp_port = int(config.get("smtp_port") or 587)

    message = EmailMessage()
    message["Subject"] = f"Вакансии, отобранные ИИ: {len(vacancies)}"
    message["From"] = username
    message["To"] = recipient
    message.set_content(_digest_text(vacancies))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise NotifyError(f"Не удалось отправить уведомление: {error}") from error


def _digest_text(vacancies: list[dict[str, Any]]) -> str:
    ranked = sorted(vacancies, key=_vacancy_score, reverse=True)
    chunks = ["Вакансии, отобранные ИИ:\n"]
    for index, vacancy in enumerate(ranked, 1):
        chunks.append(
            "\n".join([
                f"{index}.",
                f"Название вакансии: {vacancy.get('title') or vacancy.get('url') or 'Без названия'}",
                f"Компания: {vacancy.get('company') or 'не указана'}",
                f"Ссылка: {vacancy.get('url') or ''}",
                "",
            ])
        )
    return "\n".join(chunks)


def _vacancy_score(vacancy: dict[str, Any]) -> int:
    raw_score = (vacancy.get("match") or {}).get("score", vacancy.get("score", 0))
    try:
        return int(raw_score or 0)
    except (TypeError, ValueError):
        return 0
