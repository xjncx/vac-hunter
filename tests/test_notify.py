import unittest

from jobsearcher.notify import _digest_text


class NotifyDigestTest(unittest.TestCase):
    def test_digest_is_ranked_and_uses_compact_vacancy_format(self):
        text = _digest_text([
            {
                "title": "Middle Analyst",
                "company": "Beta",
                "url": "https://hh.ru/vacancy/2",
                "match": {"score": 70},
            },
            {
                "title": "AI HRTech Lead",
                "company": "Acme",
                "url": "https://hh.ru/vacancy/1",
                "match": {"score": 95},
            },
        ])

        self.assertLess(text.index("AI HRTech Lead"), text.index("Middle Analyst"))
        self.assertIn("Название вакансии: AI HRTech Lead", text)
        self.assertIn("Компания: Acme", text)
        self.assertIn("Ссылка: https://hh.ru/vacancy/1", text)
        self.assertNotIn("AI score:", text)
        self.assertNotIn("Локация:", text)


if __name__ == "__main__":
    unittest.main()
