from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        return connection

    def _init(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS applications (
                    vacancy_id TEXT PRIMARY KEY,
                    vacancy_name TEXT NOT NULL,
                    employer_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    response TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS vacancies (
                    url TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    company TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    score INTEGER,
                    ai_evaluated_at TEXT,
                    verdict TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    reasons TEXT NOT NULL DEFAULT '[]',
                    risks TEXT NOT NULL DEFAULT '[]',
                    missing_skills TEXT NOT NULL DEFAULT '[]',
                    sources TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            for column, definition in {
                "score": "INTEGER",
                "ai_evaluated_at": "TEXT",
                "verdict": "TEXT NOT NULL DEFAULT ''",
                "summary": "TEXT NOT NULL DEFAULT ''",
                "reasons": "TEXT NOT NULL DEFAULT '[]'",
                "risks": "TEXT NOT NULL DEFAULT '[]'",
                "missing_skills": "TEXT NOT NULL DEFAULT '[]'",
                "sources": "TEXT NOT NULL DEFAULT '[]'",
            }.items():
                try:
                    db.execute(f"ALTER TABLE vacancies ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError:
                    pass

    def set_json(self, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def get_json(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def save_application(self, vacancy: dict[str, Any], status: str, message: str, response: str = "") -> None:
        employer = vacancy.get("employer") or {}
        with self.connect() as db:
            db.execute("""
                INSERT INTO applications(vacancy_id,vacancy_name,employer_name,status,message,response)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(vacancy_id) DO UPDATE SET
                    status=excluded.status, message=excluded.message, response=excluded.response,
                    updated_at=CURRENT_TIMESTAMP
            """, (str(vacancy["id"]), vacancy.get("name", ""), employer.get("name", ""), status, message, response))

    def list_applications(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM applications ORDER BY updated_at DESC LIMIT 200").fetchall()
        return [dict(row) for row in rows]

    def save_vacancy(self, vacancy: dict[str, Any], source: str = "") -> None:
        url = str(vacancy.get("url", ""))
        sources = self._merged_sources(url, source)
        with self.connect() as db:
            db.execute("""
                INSERT INTO vacancies(url,title,company,location,description,source,sources)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                    title=excluded.title,
                    company=excluded.company,
                    location=excluded.location,
                    description=excluded.description,
                    source=excluded.source,
                    sources=excluded.sources,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                url,
                vacancy.get("title", ""),
                vacancy.get("company", ""),
                vacancy.get("location", ""),
                vacancy.get("description", ""),
                source,
                json.dumps(sources, ensure_ascii=False),
            ))

    def get_vacancy(self, url: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM vacancies WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None

    def vacancy_has_ai_match(self, url: str) -> bool:
        vacancy = self.get_vacancy(url)
        return bool(vacancy and (vacancy.get("ai_evaluated_at") or vacancy.get("score") is not None))

    def save_match(self, url: str, match: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("""
                UPDATE vacancies SET
                    score=?,
                    ai_evaluated_at=CURRENT_TIMESTAMP,
                    verdict=?,
                    summary=?,
                    reasons=?,
                    risks=?,
                    missing_skills=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE url=?
            """, (
                int(match.get("score") or 0),
                str(match.get("verdict") or ""),
                str(match.get("summary") or ""),
                json.dumps(match.get("reasons") or [], ensure_ascii=False),
                json.dumps(match.get("risks") or [], ensure_ascii=False),
                json.dumps(match.get("missing_skills") or [], ensure_ascii=False),
                url,
            ))

    def _merged_sources(self, url: str, source: str = "") -> list[str]:
        sources: list[str] = []
        existing = self.get_vacancy(url) if url else None
        if existing:
            try:
                raw_sources = json.loads(existing.get("sources") or "[]")
                if isinstance(raw_sources, list):
                    sources.extend(str(item) for item in raw_sources if str(item).strip())
            except json.JSONDecodeError:
                pass
            old_source = str(existing.get("source") or "").strip()
            if old_source:
                sources.append(old_source)
        source = source.strip()
        if source:
            sources.append(source)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in sources:
            key = item.casefold()
            if key not in seen:
                deduped.append(item)
                seen.add(key)
        return deduped

    def list_vacancies(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM vacancies ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
