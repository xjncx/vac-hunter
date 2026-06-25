from __future__ import annotations

import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

from .vacancy_page import normalize_hh_url


class EmailParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedEmail:
    subject: str
    from_address: str
    to_address: str
    date: str
    vacancy_urls: list[str]
    query: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "from": self.from_address,
            "to": self.to_address,
            "date": self.date,
            "query": self.query,
            "vacancy_urls": self.vacancy_urls,
            "vacancy_count": len(self.vacancy_urls),
        }


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key and key.lower() == "href" and value:
                self.links.append(value)


def parse_hh_email(raw: bytes) -> ParsedEmail:
    if not raw:
        raise EmailParseError("Пустое письмо")

    message = BytesParser(policy=policy.default).parsebytes(raw)
    subject = str(message.get("subject") or "")
    from_address = str(message.get("from") or "")
    to_address = str(message.get("to") or "")
    date = str(message.get("date") or "")

    bodies = _message_bodies(message)
    if not bodies:
        raise EmailParseError("В письме не найдено текстовое или HTML-содержимое")

    links: list[str] = []
    for body in bodies:
        links.extend(_extract_links(body))
        links.extend(match.group(0) for match in re.finditer(r"https://hh\.ru/vacancy/\d+[^\s\"'<)]+", body))

    vacancy_urls = _unique_vacancy_urls(links)
    query = _extract_query(subject, bodies)

    return ParsedEmail(
        subject=subject,
        from_address=from_address,
        to_address=to_address,
        date=date,
        query=query,
        vacancy_urls=vacancy_urls,
    )


def _message_bodies(message) -> list[str]:
    bodies: list[str] = []
    if message.is_multipart():
        parts = message.walk()
    else:
        parts = [message]

    for part in parts:
        content_type = part.get_content_type()
        if content_type not in {"text/html", "text/plain"}:
            continue
        try:
            content = part.get_content()
        except LookupError:
            payload = part.get_payload(decode=True) or b""
            content = payload.decode("utf-8", errors="replace")
        if isinstance(content, str) and content.strip():
            bodies.append(content)
    return bodies


def _extract_links(body: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(body)
    return parser.links


def _unique_vacancy_urls(links: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for link in links:
        if "/vacancy/" not in link or "hh.ru" not in link:
            continue
        try:
            clean = normalize_hh_url(link)
        except Exception:
            continue
        if clean not in seen:
            urls.append(clean)
            seen.add(clean)
    return urls


def _extract_query(subject: str, bodies: list[str]) -> str:
    subject_match = re.search(r"подписк[ае]:\s*(.+)$", subject, flags=re.IGNORECASE)
    if subject_match:
        return subject_match.group(1).strip()

    text = " ".join(re.sub(r"<[^>]+>", " ", body) for body in bodies)
    text = re.sub(r"\s+", " ", text)
    body_match = re.search(r"Новые вакансии по запросу:\s*(.+?)(?:\s{2,}|$)", text, flags=re.IGNORECASE)
    return body_match.group(1).strip() if body_match else ""
