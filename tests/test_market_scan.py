import unittest
from unittest.mock import patch

from jobsearcher.server import fetch_hh_search_urls, market_query, search_query_variants, vacancy_match_score


class MarketScanTest(unittest.TestCase):
    def test_market_query_combines_roles_and_skills(self):
        query = market_query({
            "desired_roles": "HRTech product manager",
            "desired_skills": "AI, L&D",
        })

        self.assertEqual(query, "HRTech product manager AI, L&D")

    def test_vacancy_match_score_tolerates_missing_or_invalid_score(self):
        self.assertEqual(vacancy_match_score({"match": {"score": "bad"}}, default=42), 42)
        self.assertEqual(vacancy_match_score({"score": 88}), 88)

    def test_fetch_hh_search_urls_extracts_unique_links(self):
        class Response:
            headers = type("Headers", (), {"get_content_charset": lambda self: "utf-8"})()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b"""
                    <a href="https://hh.ru/vacancy/1">One</a>
                    <a href="https://hh.ru/vacancy/1?from=search">Duplicate</a>
                    <a href="/vacancy/2">Two</a>
                """

        with patch("jobsearcher.server.urllib.request.urlopen", return_value=Response()):
            self.assertEqual(fetch_hh_search_urls(query="HRTech", limit=2), [
                "https://hh.ru/vacancy/1",
                "https://hh.ru/vacancy/2",
            ])

    def test_search_query_variants_split_mixed_query(self):
        self.assertEqual(search_query_variants("ИИ HR, automation; elearning"), [
            "ИИ HR, automation; elearning",
            "ИИ HR",
            "automation",
            "elearning",
        ])


if __name__ == "__main__":
    unittest.main()
