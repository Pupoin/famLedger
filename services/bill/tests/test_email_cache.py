import unittest

from backend.ingest.db import email_fingerprint


class EmailCacheTests(unittest.TestCase):
    def test_same_mail_with_new_graph_id_keeps_identity(self):
        message = {
            "id": "graph-one", "subject": "账户变动通知",
            "receivedDateTime": "2026-09-25T01:00:00Z",
            "from": {"emailAddress": {"address": "BANK@example.com"}},
            "body": {"content": "交易全文"},
        }
        copied = {**message, "id": "graph-two"}
        self.assertEqual(email_fingerprint(message), email_fingerprint(copied))
        self.assertNotEqual(email_fingerprint(message),
                            email_fingerprint({**message, "body": {"content": "另一笔交易"}}))


if __name__ == "__main__":
    unittest.main()
