from __future__ import annotations

import unittest

from jobsearcher.vacancy_page import normalize_hh_url, parse_vacancy_page


class VacancyPageTest(unittest.TestCase):
    def test_normalizes_hh_tracking_url(self) -> None:
        self.assertEqual(
            normalize_hh_url("https://hh.ru/vacancy/133299381?utm_source=email&loginkey=secret"),
            "https://hh.ru/vacancy/133299381",
        )

    def test_parses_jobposting_json_ld(self) -> None:
        page = """
            <html>
              <head>
                <script type="application/ld+json">
                {
                  "@context": "https://schema.org",
                  "@type": "JobPosting",
                  "title": "Golang разработчик",
                  "hiringOrganization": {"name": "Рога и Копыта"},
                  "jobLocation": {
                    "address": {
                      "addressLocality": "Москва",
                      "streetAddress": "Тверская, 1"
                    }
                  },
                  "description": "<p>Писать сервисы на Go.</p><p>PostgreSQL, Docker.</p>"
                }
                </script>
              </head>
            </html>
        """

        vacancy = parse_vacancy_page(page, "https://hh.ru/vacancy/123?x=1")

        self.assertEqual(vacancy.title, "Golang разработчик")
        self.assertEqual(vacancy.company, "Рога и Копыта")
        self.assertEqual(vacancy.location, "Москва, Тверская, 1")
        self.assertEqual(vacancy.url, "https://hh.ru/vacancy/123")
        self.assertIn("Писать сервисы на Go", vacancy.description)
        self.assertIn("PostgreSQL", vacancy.description)


if __name__ == "__main__":
    unittest.main()
