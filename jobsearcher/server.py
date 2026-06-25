from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Database
from .ai_matcher import AIMatchError, evaluate_vacancy
from .email_parser import EmailParseError, parse_hh_email
from .hh import HHClient, HHError
from .mailbox import MailboxConfig, MailboxError, fetch_hh_emails
from .notify import NotifyError, send_vacancy_digest
from .scoring import SearchProfile, score_vacancy
from .vacancy_page import VacancyPageError, fetch_and_parse_vacancy

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.database)

    def client(self) -> HHClient:
        tokens = self.db.get_json("tokens", {}) or {}
        return HHClient(self.settings, tokens.get("access_token", ""))

    def sync_mail(self, *, limit: int = 50, fetch_descriptions: bool = True) -> dict[str, Any]:
        config = self.db.get_json("service_config", {}) or {}
        emails = fetch_hh_emails(MailboxConfig.from_dict(config), limit=limit)
        vacancies = []
        errors = []
        for email_item in emails:
            for url in email_item.vacancy_urls:
                existing = self.db.get_vacancy(url)
                if fetch_descriptions:
                    if existing and existing.get("description") and self.db.vacancy_has_ai_match(url):
                        self.db.save_vacancy(existing, source=email_item.subject)
                        vacancy = dict(existing)
                        vacancy["already_seen"] = True
                        vacancy["ai_reused"] = True
                        vacancies.append(vacancy)
                        continue
                    try:
                        vacancy = fetch_and_parse_vacancy(url, user_agent=self.settings.user_agent).as_dict()
                        vacancy["already_seen"] = bool(existing)
                        self.db.save_vacancy(vacancy, source=email_item.subject)
                        if str(config.get("ai_enabled", "")).lower() in {"1", "true", "yes", "on"}:
                            if self.db.vacancy_has_ai_match(url):
                                refreshed = self.db.get_vacancy(url) or {}
                                vacancy.update({
                                    "score": refreshed.get("score"),
                                    "verdict": refreshed.get("verdict", ""),
                                    "summary": refreshed.get("summary", ""),
                                    "reasons": refreshed.get("reasons", "[]"),
                                    "risks": refreshed.get("risks", "[]"),
                                    "missing_skills": refreshed.get("missing_skills", "[]"),
                                    "ai_evaluated_at": refreshed.get("ai_evaluated_at"),
                                    "ai_reused": True,
                                })
                            else:
                                match = evaluate_vacancy(
                                    api_key=self.settings.deepseek_api_key,
                                    model=self.settings.deepseek_model,
                                    vacancy=vacancy,
                                    resume_text=str(config.get("resume_text") or ""),
                                    desired_roles=str(config.get("desired_roles") or ""),
                                    desired_skills=str(config.get("desired_skills") or ""),
                                    excluded_terms=str(config.get("excluded_terms") or ""),
                                ).as_dict()
                                vacancy["match"] = match
                                self.db.save_match(vacancy["url"], match)
                        vacancies.append(vacancy)
                    except (VacancyPageError, AIMatchError) as error:
                        errors.append({"url": url, "error": str(error)})
                else:
                    vacancies.append({"url": url})
        threshold = int(config.get("match_threshold") or 0)
        digest_vacancies = [
            vacancy for vacancy in vacancies
            if vacancy_match_score(vacancy, default=100) >= threshold
        ]
        digest_vacancies.sort(key=vacancy_match_score, reverse=True)
        notification_sent = False
        if str(config.get("notification_email") or "").strip() and fetch_descriptions and digest_vacancies:
            send_vacancy_digest(config, digest_vacancies)
            notification_sent = True
        self.db.set_json("last_sync", {
            "ts": int(time.time()),
            "emails": len(emails),
            "vacancies": len(vacancies),
            "errors": errors,
            "notification_sent": notification_sent,
        })
        return {
            "emails": [item.as_dict() for item in emails],
            "vacancies": vacancies,
            "errors": errors,
            "notification_sent": notification_sent,
        }

    def scan_market(self, *, limit: int | None = None) -> dict[str, Any]:
        config = self.db.get_json("service_config", {}) or {}
        limit = max(1, min(int(limit or config.get("market_scan_limit") or 30), 100))
        query = market_query(config)
        if not query:
            raise ValueError("Укажите желаемые роли или ключевые навыки для сканирования рынка")

        result = self.client().search({
            "text": query,
            "area": "113",
            "per_page": limit,
            "order_by": "publication_time",
        })
        vacancies: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        for item in result.get("items", [])[:limit]:
            url = str(item.get("alternate_url") or item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            existing = self.db.get_vacancy(url)
            try:
                if existing and existing.get("description") and self.db.vacancy_has_ai_match(url):
                    vacancy = dict(existing)
                    vacancy["ai_reused"] = True
                else:
                    vacancy = fetch_and_parse_vacancy(url, user_agent=self.settings.user_agent).as_dict()
                    self.db.save_vacancy(vacancy, source="market scan")
                    if str(config.get("ai_enabled", "")).lower() in {"1", "true", "yes", "on"}:
                        match = evaluate_vacancy(
                            api_key=self.settings.deepseek_api_key,
                            model=self.settings.deepseek_model,
                            vacancy=vacancy,
                            resume_text=str(config.get("resume_text") or ""),
                            desired_roles=str(config.get("desired_roles") or ""),
                            desired_skills=str(config.get("desired_skills") or ""),
                            excluded_terms=str(config.get("excluded_terms") or ""),
                        ).as_dict()
                        vacancy["match"] = match
                        self.db.save_match(vacancy["url"], match)
                vacancies.append(vacancy)
            except (VacancyPageError, AIMatchError) as error:
                errors.append({"url": url, "error": str(error)})

        threshold = int(config.get("match_threshold") or 0)
        digest_vacancies = [
            vacancy for vacancy in vacancies
            if vacancy_match_score(vacancy, default=100) >= threshold
        ]
        digest_vacancies.sort(key=vacancy_match_score, reverse=True)
        notification_sent = False
        if str(config.get("notification_email") or "").strip() and digest_vacancies:
            send_vacancy_digest(config, digest_vacancies)
            notification_sent = True

        self.db.set_json("last_sync", {
            "ts": int(time.time()),
            "mode": "market_scan",
            "emails": 0,
            "vacancies": len(vacancies),
            "errors": errors,
            "notification_sent": notification_sent,
        })
        return {
            "query": query,
            "found": result.get("found", len(vacancies)),
            "vacancies": vacancies,
            "errors": errors,
            "notification_sent": notification_sent,
        }


def vacancy_match_score(vacancy: dict[str, Any], *, default: int = 0) -> int:
    raw_score = (vacancy.get("match") or {}).get("score", vacancy.get("score", default))
    try:
        return int(raw_score if raw_score is not None else default)
    except (TypeError, ValueError):
        return default


def market_query(config: dict[str, Any]) -> str:
    parts = [
        str(config.get("desired_roles") or "").strip(),
        str(config.get("desired_skills") or "").strip(),
    ]
    return " ".join(part for part in parts if part)


class Handler(BaseHTTPRequestHandler):
    app: App

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        if not self.authorized():
            return self.auth_required()
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/status":
                tokens = self.app.db.get_json("tokens", {}) or {}
                return self.json({"connected": bool(tokens.get("access_token")), "send_enabled": self.app.settings.send_enabled,
                                  "oauth_configured": bool(self.app.settings.client_id and self.app.settings.client_secret),
                                  "user_agent_configured": bool(self.app.settings.user_agent and "replace-with" not in self.app.settings.user_agent)})
            if parsed.path == "/api/applications":
                return self.json({"items": self.app.db.list_applications()})
            if parsed.path == "/api/service-config":
                return self.json(mask_config(self.app.db.get_json("service_config", {}) or {}))
            if parsed.path == "/api/vacancies":
                return self.json({"items": self.app.db.list_vacancies()})
            if parsed.path == "/api/last-sync":
                return self.json(self.app.db.get_json("last_sync", {}) or {})
            if parsed.path == "/api/resumes":
                return self.json({"items": self.app.client().resumes()})
            if parsed.path == "/oauth/start":
                if not self.app.settings.client_id:
                    return self.json({"error": "Заполните HH_CLIENT_ID в .env"}, 400)
                url, state = self.app.client().authorization_url()
                self.app.db.set_json("oauth_state", state)
                return self.redirect(url)
            if parsed.path == "/oauth/callback":
                query = urllib.parse.parse_qs(parsed.query)
                if query.get("state", [""])[0] != self.app.db.get_json("oauth_state", ""):
                    return self.json({"error": "Некорректный OAuth state"}, 400)
                code = query.get("code", [""])[0]
                if not code:
                    return self.json({"error": query.get("error", ["Код OAuth не получен"])[0]}, 400)
                tokens = self.app.client().exchange_code(code)
                self.app.db.set_json("tokens", tokens)
                return self.redirect("/?connected=1")
            if parsed.path == "/":
                return self.file(WEB / "index.html")
            if parsed.path.startswith("/static/"):
                path = (WEB / parsed.path.removeprefix("/static/")).resolve()
                if WEB.resolve() not in path.parents:
                    return self.json({"error": "Not found"}, 404)
                return self.file(path)
            return self.json({"error": "Not found"}, 404)
        except HHError as error:
            return self.json({"error": str(error), "details": error.payload}, error.status)
        except Exception as error:
            return self.json({"error": str(error)}, 500)

    def do_POST(self) -> None:
        if not self.authorized():
            return self.auth_required()
        parsed = urllib.parse.urlparse(self.path)
        try:
            payload = self.body_json()
            if parsed.path == "/api/service-config":
                current = self.app.db.get_json("service_config", {}) or {}
                merged = dict(current)
                for key in [
                    "imap_host", "imap_port", "mail_username", "mail_folder", "mail_sender_filter",
                    "notification_email", "resume_text", "desired_roles", "desired_skills",
                    "excluded_terms", "market_scan_limit", "match_threshold", "ai_enabled",
                    "auto_sync_enabled", "sync_interval_minutes",
                ]:
                    if key in payload:
                        merged[key] = payload.get(key)
                if payload.get("mail_password"):
                    merged["mail_password"] = payload.get("mail_password")
                validation_errors = validate_service_config(merged)
                if validation_errors:
                    return self.json({"error": "Заполните обязательные поля", "details": validation_errors}, 400)
                self.app.db.set_json("service_config", merged)
                return self.json({"status": "saved", "config": mask_config(merged)})
            if parsed.path == "/api/search":
                profile = SearchProfile.from_payload(payload)
                if not profile.query:
                    return self.json({"error": "Укажите поисковый запрос"}, 400)
                params = {"text": profile.query, "area": profile.area, "per_page": min(int(payload.get("limit") or 30), 100),
                          "order_by": "publication_time", "only_with_salary": bool(payload.get("only_with_salary"))}
                if profile.salary_min:
                    params["salary"] = profile.salary_min
                result = self.app.client().search(params)
                items = []
                for vacancy in result.get("items", []):
                    score, reasons = score_vacancy(vacancy, profile)
                    vacancy["match_score"] = score
                    vacancy["match_reasons"] = reasons
                    items.append(vacancy)
                items.sort(key=lambda item: item["match_score"], reverse=True)
                return self.json({"items": items, "found": result.get("found", len(items))})
            if parsed.path == "/api/apply":
                vacancy_id = str(payload.get("vacancy_id", ""))
                resume_id = str(payload.get("resume_id", ""))
                message = str(payload.get("message", ""))
                vacancy = self.app.client().vacancy(vacancy_id)
                if "got_response" in (vacancy.get("relations") or []):
                    return self.json({"error": "На эту вакансию уже был отклик"}, 409)
                if not self.app.settings.send_enabled:
                    self.app.db.save_application(vacancy, "dry_run", message)
                    return self.json({"status": "dry_run", "message": "Отклик сохранён, но отправка отключена"})
                if not resume_id:
                    return self.json({"error": "Укажите ID резюме"}, 400)
                suitable = self.app.client().suitable_resumes(vacancy_id)
                suitable_ids = {str(item.get("id")) for item in suitable}
                if resume_id not in suitable_ids:
                    return self.json({"error": "Выбранное резюме не подходит для отклика по данным HH"}, 400)
                result = self.app.client().apply(vacancy_id, resume_id, message)
                self.app.db.save_application(vacancy, "sent", message, json.dumps(result, ensure_ascii=False))
                return self.json({"status": "sent", "result": result})
            if parsed.path == "/api/vacancy-page":
                url = str(payload.get("url", "")).strip()
                if not url:
                    return self.json({"error": "Укажите ссылку на вакансию HH"}, 400)
                vacancy = fetch_and_parse_vacancy(url, user_agent=self.app.settings.user_agent)
                return self.json(vacancy.as_dict())
            if parsed.path == "/api/vacancy/evaluate":
                config = self.app.db.get_json("service_config", {}) or {}
                vacancy = dict(payload.get("vacancy") or {})
                if not vacancy.get("url") and payload.get("url"):
                    vacancy = fetch_and_parse_vacancy(str(payload.get("url")), user_agent=self.app.settings.user_agent).as_dict()
                match = evaluate_vacancy(
                    api_key=self.app.settings.deepseek_api_key,
                    model=self.app.settings.deepseek_model,
                    vacancy=vacancy,
                    resume_text=str(config.get("resume_text") or ""),
                    desired_roles=str(config.get("desired_roles") or ""),
                    desired_skills=str(config.get("desired_skills") or ""),
                    excluded_terms=str(config.get("excluded_terms") or ""),
                ).as_dict()
                if vacancy.get("url"):
                    self.app.db.save_vacancy(vacancy, source="manual")
                    self.app.db.save_match(str(vacancy["url"]), match)
                return self.json({"vacancy": vacancy, "match": match})
            if parsed.path == "/api/email/parse":
                content_base64 = str(payload.get("content_base64", ""))
                if not content_base64:
                    return self.json({"error": "Передайте .eml файл"}, 400)
                try:
                    raw_email = base64.b64decode(content_base64, validate=True)
                except ValueError as error:
                    raise ValueError("Не удалось прочитать .eml файл") from error
                parsed_email = parse_hh_email(raw_email)
                result = parsed_email.as_dict()
                if bool(payload.get("fetch_descriptions")):
                    vacancies = []
                    errors = []
                    for url in parsed_email.vacancy_urls:
                        try:
                            vacancies.append(fetch_and_parse_vacancy(url, user_agent=self.app.settings.user_agent).as_dict())
                        except VacancyPageError as error:
                            errors.append({"url": url, "error": str(error)})
                    result["vacancies"] = vacancies
                    result["errors"] = errors
                return self.json(result)
            if parsed.path == "/api/mail/sync":
                limit = min(int(payload.get("limit") or 50), 100)
                fetch_descriptions = bool(payload.get("fetch_descriptions"))
                return self.json(self.app.sync_mail(limit=limit, fetch_descriptions=fetch_descriptions))
            if parsed.path == "/api/market/scan":
                limit = min(int(payload.get("limit") or 0), 100) or None
                return self.json(self.app.scan_market(limit=limit))
            return self.json({"error": "Not found"}, 404)
        except HHError as error:
            return self.json({"error": str(error), "details": error.payload}, error.status)
        except VacancyPageError as error:
            return self.json({"error": str(error)}, 400)
        except EmailParseError as error:
            return self.json({"error": str(error)}, 400)
        except MailboxError as error:
            return self.json({"error": str(error)}, 400)
        except NotifyError as error:
            return self.json({"error": str(error)}, 400)
        except AIMatchError as error:
            return self.json({"error": str(error)}, 400)
        except (ValueError, TypeError) as error:
            return self.json({"error": str(error)}, 400)
        except Exception as error:
            return self.json({"error": str(error)}, 500)

    def body_json(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1_000_000:
            raise ValueError("Слишком большой запрос")
        return json.loads(self.rfile.read(size) or b"{}")

    def authorized(self) -> bool:
        password = self.app.settings.admin_password
        if not password:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header.removeprefix("Basic ").strip()).decode("utf-8")
        except Exception:
            return False
        username, _, provided = raw.partition(":")
        return username == self.app.settings.admin_user and secrets.compare_digest(provided, password)

    def auth_required(self) -> None:
        body = b"Authentication required"
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Vacancy Hunter"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def file(self, path: Path) -> None:
        if not path.is_file():
            return self.json({"error": "Not found"}, 404)
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", (mimetypes.guess_type(path.name)[0] or "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, url: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", url)
        self.end_headers()


def mask_config(config: dict[str, Any]) -> dict[str, Any]:
    masked = dict(config)
    if masked.get("mail_password"):
        masked["mail_password"] = "********"
    return masked


def validate_service_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def enabled(key: str) -> bool:
        return str(config.get(key, "")).lower() in {"1", "true", "yes", "on"}

    required = {
        "imap_host": "IMAP host",
        "imap_port": "IMAP port",
        "mail_username": "Почта, которую читать",
        "mail_password": "App password почты",
        "mail_sender_filter": "Фильтр отправителя",
        "notification_email": "Email для уведомлений",
        "desired_roles": "Желаемые роли",
        "desired_skills": "Ключевые навыки",
        "excluded_terms": "Стоп-слова",
        "resume_text": "Резюме / профиль кандидата",
    }
    if enabled("auto_sync_enabled"):
        required["sync_interval_minutes"] = "Интервал проверки"

    for key, label in required.items():
        if not str(config.get(key) or "").strip():
            errors.append(label)

    if str(config.get("imap_port") or "").strip():
        try:
            port = int(config.get("imap_port") or 0)
            if port <= 0:
                errors.append("IMAP port должен быть положительным числом")
        except (TypeError, ValueError):
            errors.append("IMAP port должен быть положительным числом")

    try:
        threshold = int(config.get("match_threshold") or 75)
        if threshold < 0 or threshold > 100:
            errors.append("Порог совпадения должен быть от 0 до 100")
    except (TypeError, ValueError):
        errors.append("Порог совпадения должен быть от 0 до 100")

    try:
        scan_limit = int(config.get("market_scan_limit") or 30)
        if scan_limit < 1 or scan_limit > 100:
            errors.append("Количество вакансий для оценки ИИ должно быть от 1 до 100")
    except (TypeError, ValueError):
        errors.append("Количество вакансий для оценки ИИ должно быть от 1 до 100")

    if enabled("auto_sync_enabled"):
        try:
            interval = int(config.get("sync_interval_minutes") or 0)
            if interval < 5:
                errors.append("Интервал проверки должен быть не меньше 5 минут")
        except (TypeError, ValueError):
            errors.append("Интервал проверки должен быть не меньше 5 минут")

    return errors


def start_background_sync(app: App) -> None:
    def worker() -> None:
        while True:
            config = app.db.get_json("service_config", {}) or {}
            enabled = str(config.get("auto_sync_enabled", "")).lower() in {"1", "true", "yes", "on"}
            interval_minutes = max(5, int(config.get("sync_interval_minutes") or 15))
            if enabled:
                try:
                    app.sync_mail(limit=50, fetch_descriptions=True)
                except Exception as error:
                    app.db.set_json("last_sync", {
                        "ts": int(time.time()),
                        "emails": 0,
                        "vacancies": 0,
                        "errors": [{"error": str(error)}],
                        "notification_sent": False,
                    })
            time.sleep(interval_minutes * 60)

    thread = threading.Thread(target=worker, name="mail-sync", daemon=True)
    thread.start()


def run() -> None:
    settings = Settings.from_env()
    Handler.app = App(settings)
    start_background_sync(Handler.app)
    server = ThreadingHTTPServer((settings.host, settings.port), Handler)
    print(f"JobSearcher: http://{settings.host}:{settings.port}")
    print("Реальная отправка:", "ВКЛЮЧЕНА" if settings.send_enabled else "выключена (dry-run)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
