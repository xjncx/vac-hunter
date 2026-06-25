from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _terms(value: str) -> list[str]:
    return [part.strip().casefold() for part in re.split(r"[,;\n]", value) if part.strip()]


@dataclass(frozen=True)
class SearchProfile:
    query: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    salary_min: int = 0
    area: str = "113"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SearchProfile":
        return cls(
            query=str(payload.get("query", "")).strip(),
            include=tuple(_terms(str(payload.get("include", "")))),
            exclude=tuple(_terms(str(payload.get("exclude", "")))),
            salary_min=max(0, int(payload.get("salary_min") or 0)),
            area=str(payload.get("area") or "113"),
        )


def score_vacancy(vacancy: dict[str, Any], profile: SearchProfile) -> tuple[int, list[str]]:
    name = str(vacancy.get("name") or "")
    snippet = vacancy.get("snippet") or {}
    text = " ".join((name, str(snippet.get("requirement") or ""), str(snippet.get("responsibility") or ""))).casefold()
    score = 45
    reasons: list[str] = []

    query_words = [word for word in re.findall(r"[\w+#.-]+", profile.query.casefold()) if len(word) > 1]
    matched_query = sum(word in text for word in query_words)
    if query_words:
        score += round(20 * matched_query / len(query_words))
        reasons.append(f"совпадение запроса: {matched_query}/{len(query_words)}")

    matched_include = [term for term in profile.include if term in text]
    if profile.include:
        score += round(25 * len(matched_include) / len(profile.include))
        reasons.append("навыки: " + (", ".join(matched_include) or "нет совпадений"))

    blocked = [term for term in profile.exclude if term in text]
    if blocked:
        score -= 100
        reasons.append("стоп-слова: " + ", ".join(blocked))

    salary = vacancy.get("salary") or {}
    salary_from = salary.get("from") or 0
    salary_to = salary.get("to") or 0
    if profile.salary_min and max(salary_from, salary_to) >= profile.salary_min:
        score += 10
        reasons.append("зарплата соответствует")
    elif profile.salary_min and salary and max(salary_from, salary_to) < profile.salary_min:
        score -= 25
        reasons.append("зарплата ниже минимума")

    if "got_response" in (vacancy.get("relations") or []):
        score = -100
        reasons.append("уже откликались")

    return max(0, min(100, score)), reasons

