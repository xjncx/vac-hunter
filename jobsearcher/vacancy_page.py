from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


class VacancyPageError(RuntimeError):
    pass


@dataclass(frozen=True)
class VacancyPage:
    title: str
    company: str
    location: str
    url: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "description": self.description,
        }


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._script_type = ""
        self._script_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "script":
            self._script_type = attr.get("type", "").lower()
            self._script_parts = []
        if tag == "meta":
            name = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content", "").strip()
            if name and content:
                self.meta[name] = html.unescape(content)
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._script_type == "application/ld+json":
            payload = "".join(self._script_parts).strip()
            if payload:
                self.json_ld.append(payload)
            self._script_type = ""
            self._script_parts = []
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._script_type == "application/ld+json":
            self._script_parts.append(data)
            return
        if not self._skip_depth:
            self.text_parts.append(data)

    def visible_text(self) -> str:
        return normalize_text(" ".join(self.text_parts))


def normalize_hh_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    match = re.search(r"/vacancy/(\d+)", parsed.path)
    if not match:
        raise VacancyPageError(f"Не похоже на ссылку вакансии HH: {url}")
    return f"https://hh.ru/vacancy/{match.group(1)}"


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n\n", value)
    return value.strip()


def html_to_text(value: str) -> str:
    parser = _TextHTMLParser()
    parser.feed(value or "")
    return parser.visible_text()


def fetch_vacancy_page(url: str, *, user_agent: str = "", timeout: int = 25) -> str:
    clean_url = normalize_hh_url(url)
    headers = {
        "User-Agent": user_agent or "JobSearcher/0.1 (+local; email parser)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6",
    }
    request = urllib.request.Request(clean_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as error:
        raise VacancyPageError(f"HH вернул HTTP {error.code} для {clean_url}") from error
    except urllib.error.URLError as error:
        raise VacancyPageError(f"Не удалось открыть {clean_url}: {error.reason}") from error


def parse_vacancy_page(page_html: str, url: str) -> VacancyPage:
    clean_url = normalize_hh_url(url)
    parser = _TextHTMLParser()
    parser.feed(page_html)

    structured = _extract_jobposting(parser.json_ld)
    title = _first_text(
        structured.get("title"),
        parser.meta.get("og:title"),
        _match_text(page_html, r'data-qa=["\']vacancy-title["\'][^>]*>(.*?)</'),
        _match_text(page_html, r"<h1[^>]*>(.*?)</h1>"),
    )
    company = _first_text(
        structured.get("company"),
        parser.meta.get("og:site_name") if parser.meta.get("og:site_name", "").lower() != "hh.ru" else "",
        _match_text(page_html, r'data-qa=["\']vacancy-company-name["\'][^>]*>(.*?)</'),
        _match_text(page_html, r'data-qa=["\']vacancy-serp__vacancy-employer["\'][^>]*>(.*?)</'),
    )
    location = _first_text(
        structured.get("location"),
        _match_text(page_html, r'data-qa=["\']vacancy-view-raw-address["\'][^>]*>(.*?)</'),
        _match_text(page_html, r'data-qa=["\']vacancy-view-location["\'][^>]*>(.*?)</'),
    )
    description = _first_text(
        structured.get("description"),
        _match_text(page_html, r'data-qa=["\']vacancy-description["\'][^>]*>(.*?)</div>\s*</div>'),
        _match_text(page_html, r'<div[^>]+class=["\'][^"\']*vacancy-description[^"\']*["\'][^>]*>(.*?)</div>'),
        parser.meta.get("description"),
    )

    return VacancyPage(
        title=_clean_title(title),
        company=company,
        location=location,
        url=clean_url,
        description=description,
    )


def fetch_and_parse_vacancy(url: str, *, user_agent: str = "", timeout: int = 25) -> VacancyPage:
    return parse_vacancy_page(fetch_vacancy_page(url, user_agent=user_agent, timeout=timeout), url)


def _extract_jobposting(json_ld_items: list[str]) -> dict[str, str]:
    for raw in json_ld_items:
        for item in _iter_json_items(raw):
            item_type = item.get("@type")
            if isinstance(item_type, list):
                is_job = "JobPosting" in item_type
            else:
                is_job = item_type == "JobPosting"
            if not is_job:
                continue
            organization = item.get("hiringOrganization") or {}
            location = item.get("jobLocation") or item.get("applicantLocationRequirements") or {}
            return {
                "title": str(item.get("title") or ""),
                "company": _nested_name(organization),
                "location": _format_location(location),
                "description": html_to_text(str(item.get("description") or "")),
            }
    return {}


def _iter_json_items(raw: str) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(decoded, dict) and isinstance(decoded.get("@graph"), list):
        decoded = decoded["@graph"]
    if isinstance(decoded, dict):
        return [decoded]
    if isinstance(decoded, list):
        return [item for item in decoded if isinstance(item, dict)]
    return []


def _nested_name(value: Any) -> str:
    if isinstance(value, dict):
        return normalize_text(str(value.get("name") or ""))
    return normalize_text(str(value or ""))


def _format_location(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(filter(None, (_format_location(item) for item in value)))
    if not isinstance(value, dict):
        return normalize_text(str(value or ""))
    address = value.get("address") or value
    if not isinstance(address, dict):
        return normalize_text(str(address or ""))
    parts = [
        address.get("addressLocality"),
        address.get("streetAddress"),
        address.get("addressRegion"),
    ]
    clean_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        clean = normalize_text(str(part or ""))
        key = clean.casefold()
        if clean and key not in seen:
            clean_parts.append(clean)
            seen.add(key)
    return normalize_text(", ".join(clean_parts))


def _match_text(source: str, pattern: str) -> str:
    match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return html_to_text(match.group(1))


def _first_text(*values: str | None) -> str:
    for value in values:
        clean = normalize_text(value or "")
        if clean:
            return clean
    return ""


def _clean_title(title: str) -> str:
    title = normalize_text(title)
    title = re.sub(r"\s+вакансия\s+.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+\|\s+hh\.ru$", "", title, flags=re.IGNORECASE)
    return title.strip()
