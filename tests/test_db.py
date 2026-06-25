from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jobsearcher.db import Database


class DatabaseTest(unittest.TestCase):
    def test_vacancy_ai_match_and_sources_are_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(str(Path(tmp) / "test.db"))
            vacancy = {
                "url": "https://hh.ru/vacancy/1",
                "title": "Go developer",
                "company": "Acme",
                "location": "Москва",
                "description": "Go, PostgreSQL",
            }

            db.save_vacancy(vacancy, source="Вакансии по подписке: golang")
            db.save_match(vacancy["url"], {"score": 91, "verdict": "good"})
            db.save_vacancy(vacancy, source="Вакансии по подписке: backend")

            saved = db.get_vacancy(vacancy["url"])
            self.assertIsNotNone(saved)
            self.assertTrue(db.vacancy_has_ai_match(vacancy["url"]))
            self.assertEqual(saved["score"], 91)
            self.assertIn("golang", saved["sources"])
            self.assertIn("backend", saved["sources"])


if __name__ == "__main__":
    unittest.main()
