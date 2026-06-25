import unittest

from jobsearcher.scoring import SearchProfile, score_vacancy


class ScoringTests(unittest.TestCase):
    def test_matching_skills_raise_score(self):
        profile = SearchProfile("Python developer", ("fastapi", "postgresql"), (), 150000)
        vacancy = {"name": "Python developer", "snippet": {"requirement": "FastAPI, PostgreSQL"},
                   "salary": {"from": 180000}, "relations": []}
        score, reasons = score_vacancy(vacancy, profile)
        self.assertGreaterEqual(score, 90)
        self.assertTrue(any("навыки" in reason for reason in reasons))

    def test_excluded_term_blocks_vacancy(self):
        profile = SearchProfile("developer", (), ("1с",))
        vacancy = {"name": "Разработчик 1С", "snippet": {}, "relations": []}
        self.assertEqual(score_vacancy(vacancy, profile)[0], 0)

    def test_existing_response_blocks_vacancy(self):
        profile = SearchProfile("developer")
        vacancy = {"name": "Developer", "snippet": {}, "relations": ["got_response"]}
        self.assertEqual(score_vacancy(vacancy, profile)[0], 0)


if __name__ == "__main__":
    unittest.main()

