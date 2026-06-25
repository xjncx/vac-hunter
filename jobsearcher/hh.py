from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Settings


class HHError(RuntimeError):
    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


@dataclass
class HHClient:
    settings: Settings
    access_token: str = ""

    def authorization_url(self, state: str | None = None) -> tuple[str, str]:
        state = state or secrets.token_urlsafe(24)
        query = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "state": state,
        })
        return f"https://hh.ru/oauth/authorize?{query}", state

    def exchange_code(self, code: str) -> dict[str, Any]:
        return self._request("POST", "/token", data={
            "grant_type": "authorization_code",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "code": code,
            "redirect_uri": self.settings.redirect_uri,
        }, authenticated=False)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._request("POST", "/token", data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }, authenticated=False)

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/me")

    def resumes(self) -> list[dict[str, Any]]:
        return self._request("GET", "/resumes/mine").get("items", [])

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._request("GET", "/vacancies", params=params, authenticated=bool(self.access_token))

    def vacancy(self, vacancy_id: str) -> dict[str, Any]:
        return self._request("GET", f"/vacancies/{urllib.parse.quote(vacancy_id)}", authenticated=bool(self.access_token))

    def suitable_resumes(self, vacancy_id: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/vacancies/{urllib.parse.quote(vacancy_id)}/suitable_resumes")
        return result.get("items", [])

    def apply(self, vacancy_id: str, resume_id: str, message: str = "") -> dict[str, Any]:
        data = {"vacancy_id": vacancy_id, "resume_id": resume_id}
        if message.strip():
            data["message"] = message.strip()
        return self._request("POST", "/negotiations", data=data)

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                 data: dict[str, Any] | None = None, authenticated: bool = True) -> dict[str, Any]:
        if not self.settings.user_agent or "example.com" in self.settings.user_agent.casefold() or "replace-with" in self.settings.user_agent.casefold():
            raise HHError(400, "Укажите HH_USER_AGENT с реальным контактным email в файле .env")
        base = "https://api.hh.ru"
        if params:
            clean = {
                key: (str(value).lower() if isinstance(value, bool) else value)
                for key, value in params.items() if value not in (None, "")
            }
            path += "?" + urllib.parse.urlencode(clean, doseq=True)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        headers = {"User-Agent": self.settings.user_agent, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if authenticated:
            if not self.access_token:
                raise HHError(401, "Сначала подключите аккаунт HeadHunter")
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = urllib.request.Request(base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return {"status": response.status, "location": response.headers.get("Location")}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"status": response.status, "location": response.headers.get("Location"), "body": raw}
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw
            message = f"HeadHunter API: HTTP {error.code}"
            if error.code == 403 and isinstance(payload, dict):
                kinds = {item.get("type") for item in payload.get("errors", []) if isinstance(item, dict)}
                if kinds == {"forbidden"}:
                    message = "HeadHunter запретил запрос: проверьте VPN/прокси, доступность api.hh.ru из вашей сети или подключите OAuth"
            raise HHError(error.code, message, payload) from error
