import unittest

from jobsearcher.server import validate_service_config


VALID_CONFIG = {
    "imap_host": "imap.gmail.com",
    "imap_port": "993",
    "mail_username": "user@gmail.com",
    "mail_password": "app-password",
    "mail_sender_filter": "hh.ru",
    "notification_email": "recipient@example.com",
    "desired_roles": "HRTech product manager",
    "desired_skills": "AI, HR, analytics",
    "excluded_terms": "sales",
    "resume_text": "Candidate profile",
    "match_threshold": "75",
}


class ServiceConfigValidationTest(unittest.TestCase):
    def test_accepts_complete_config(self):
        self.assertEqual(validate_service_config(dict(VALID_CONFIG)), [])

    def test_requires_notification_email(self):
        config = dict(VALID_CONFIG, notification_email="")

        self.assertIn("Email для уведомлений", validate_service_config(config))

    def test_requires_valid_interval_when_auto_sync_enabled(self):
        config = dict(VALID_CONFIG, auto_sync_enabled="on", sync_interval_minutes="3")

        self.assertIn("Интервал проверки должен быть не меньше 5 минут", validate_service_config(config))


if __name__ == "__main__":
    unittest.main()
