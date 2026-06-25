import unittest

from jobsearcher.server import market_query, vacancy_match_score


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


if __name__ == "__main__":
    unittest.main()
