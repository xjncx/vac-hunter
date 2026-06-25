from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class AIMatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIMatchResult:
    score: int
    verdict: str
    summary: str
    reasons: list[str]
    risks: list[str]
    missing_skills: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "summary": self.summary,
            "reasons": self.reasons,
            "risks": self.risks,
            "missing_skills": self.missing_skills,
        }


def evaluate_vacancy(
    *,
    api_key: str,
    model: str,
    vacancy: dict[str, Any],
    resume_text: str,
    desired_roles: str = "",
    desired_skills: str = "",
    excluded_terms: str = "",
    timeout: int = 60,
) -> AIMatchResult:
    if not api_key:
        raise AIMatchError("Не задан DEEPSEEK_API_KEY")
    if not resume_text.strip():
        raise AIMatchError("Добавьте резюме/профиль кандидата в настройках сервиса")

    payload = {
        "model": model or "deepseek-v4-flash",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты оцениваешь вакансии для кандидата. Верни только JSON без markdown. "
                    "Формат: score 0-100, verdict one of good/maybe/bad, summary string, "
                    "reasons string[], risks string[], missing_skills string[]. "
                    "Будь строгим: если вакансия не соответствует резюме, ставь низкий score."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "candidate_resume": resume_text[:12000],
                    "desired_roles": desired_roles,
                    "desired_skills": desired_skills,
                    "excluded_terms": excluded_terms,
                    "vacancy": {
                        "title": vacancy.get("title", ""),
                        "company": vacancy.get("company", ""),
                        "location": vacancy.get("location", ""),
                        "url": vacancy.get("url", ""),
                        "description": str(vacancy.get("description", ""))[:16000],
                    },
                    "instruction": "Оцени насколько вакансия подходит кандидату и объясни кратко по-русски.",
                }, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise AIMatchError(f"DeepSeek API HTTP {error.code}: {body[:500]}") from error
    except urllib.error.URLError as error:
        raise AIMatchError(f"Не удалось обратиться к DeepSeek API: {error.reason}") from error

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise AIMatchError("DeepSeek вернул неожиданный ответ") from error

    return _parse_ai_content(content)


def _parse_ai_content(content: str) -> AIMatchResult:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise AIMatchError("DeepSeek не вернул валидный JSON") from error

    score = max(0, min(100, int(data.get("score") or 0)))
    verdict = str(data.get("verdict") or ("good" if score >= 75 else "maybe" if score >= 50 else "bad"))
    return AIMatchResult(
        score=score,
        verdict=verdict,
        summary=str(data.get("summary") or ""),
        reasons=_string_list(data.get("reasons")),
        risks=_string_list(data.get("risks")),
        missing_skills=_string_list(data.get("missing_skills")),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
