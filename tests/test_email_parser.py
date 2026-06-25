from __future__ import annotations

import unittest

from jobsearcher.email_parser import parse_hh_email


class EmailParserTest(unittest.TestCase):
    def test_extracts_unique_hh_vacancy_urls(self) -> None:
        raw = """From: "hh.ru" <noreply@hh.ru>
To: user@example.com
Subject: =?utf-8?b?0JLQsNC60LDQvdGB0LjQuCDQv9C+INC/0L7QtNC/0LjRgdC60LU6IGdvbGFuZw==?=
Content-Type: text/html; charset=utf-8

<html>
  <body>
    <a href="https://hh.ru/vacancy/123?utm_source=email&amp;loginkey=secret">One</a>
    <a href="https://hh.ru/vacancy/123?utm_content=button">Duplicate</a>
    <a href="https://hh.ru/vacancy/456?vss=1">Two</a>
  </body>
</html>
""".encode()

        parsed = parse_hh_email(raw)

        self.assertEqual(parsed.query, "golang")
        self.assertEqual(parsed.vacancy_urls, [
            "https://hh.ru/vacancy/123",
            "https://hh.ru/vacancy/456",
        ])


if __name__ == "__main__":
    unittest.main()
