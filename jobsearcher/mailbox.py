from __future__ import annotations

import imaplib
from dataclasses import dataclass
from typing import Any

from .email_parser import ParsedEmail, parse_hh_email


class MailboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailboxConfig:
    host: str = "imap.gmail.com"
    port: int = 993
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    sender_filter: str = "hh.ru"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MailboxConfig":
        return cls(
            host=str(payload.get("imap_host") or "imap.gmail.com").strip(),
            port=int(payload.get("imap_port") or 993),
            username=str(payload.get("mail_username") or "").strip(),
            password=str(payload.get("mail_password") or ""),
            folder=str(payload.get("mail_folder") or "INBOX").strip() or "INBOX",
            sender_filter=str(payload.get("mail_sender_filter") or "hh.ru").strip(),
        )


def fetch_hh_emails(config: MailboxConfig, *, limit: int = 10) -> list[ParsedEmail]:
    if not config.username or not config.password:
        raise MailboxError("Укажите логин и app password почты")

    try:
        with imaplib.IMAP4_SSL(config.host, config.port) as imap:
            imap.login(config.username, config.password)
            status, _ = imap.select(config.folder)
            if status != "OK":
                raise MailboxError(f"Не удалось открыть папку/метку почты: {config.folder}")

            query = '(FROM "hh.ru")' if config.sender_filter else "ALL"
            status, data = imap.search(None, query)
            if status != "OK":
                raise MailboxError("Не удалось найти письма в почте")

            ids = data[0].split()
            selected = ids[-limit:]
            parsed: list[ParsedEmail] = []
            for message_id in reversed(selected):
                status, fetched = imap.fetch(message_id, "(RFC822)")
                if status != "OK" or not fetched:
                    continue
                for item in fetched:
                    if isinstance(item, tuple):
                        parsed_email = parse_hh_email(item[1])
                        if parsed_email.vacancy_urls:
                            parsed.append(parsed_email)
                        break
            return parsed
    except imaplib.IMAP4.error as error:
        raise MailboxError(f"IMAP ошибка: {error}") from error
    except OSError as error:
        raise MailboxError(f"Не удалось подключиться к почте: {error}") from error
