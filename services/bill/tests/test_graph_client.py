import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from backend.ingest.graph_client import GraphMailClient


class GraphMailClientRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = GraphMailClient(
            "test-token",
            connect_timeout=2,
            read_timeout=5,
            max_retries=2,
            retry_backoff_seconds=0.25,
        )

    @staticmethod
    def response(status_code: int = 200, *, headers: dict[str, str] | None = None) -> Mock:
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        response.json.return_value = {"value": []}
        response.raise_for_status.return_value = None
        return response

    @patch("backend.ingest.graph_client.time.sleep")
    def test_retries_read_timeout_then_succeeds(self, sleep: Mock) -> None:
        self.client.session.get = Mock(side_effect=[requests.ReadTimeout("slow response"), self.response()])

        result = self.client._get("https://graph.microsoft.com/v1.0/me/messages")

        self.assertEqual(result, {"value": []})
        self.assertEqual(self.client.session.get.call_count, 2)
        self.assertEqual(self.client.session.get.call_args.kwargs["timeout"], (2, 5))
        sleep.assert_called_once_with(0.25)

    @patch("backend.ingest.graph_client.time.sleep")
    def test_retries_throttling_using_retry_after(self, sleep: Mock) -> None:
        throttled = self.response(429, headers={"Retry-After": "3"})
        self.client.session.get = Mock(side_effect=[throttled, self.response()])

        self.client._get("https://graph.microsoft.com/v1.0/me/messages")

        sleep.assert_called_once_with(3.0)
        throttled.close.assert_called_once()

    @patch("backend.ingest.graph_client.time.sleep")
    def test_does_not_retry_non_transient_http_error(self, sleep: Mock) -> None:
        unauthorized = self.response(401)
        unauthorized.raise_for_status.side_effect = requests.HTTPError("unauthorized")
        self.client.session.get = Mock(return_value=unauthorized)

        with self.assertRaises(requests.HTTPError):
            self.client._get("https://graph.microsoft.com/v1.0/me/messages")

        self.client.session.get.assert_called_once()
        sleep.assert_not_called()

    def test_incremental_scan_can_cache_all_mail_in_folder(self) -> None:
        since = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
        unrelated = {"id": "mail-1", "subject": "other", "receivedDateTime": "2026-09-25T01:00:00Z",
                     "from": {"emailAddress": {"address": "other@example.com"}}}
        with patch.object(self.client, "_get", return_value={"value": [unrelated]}) as get:
            messages = self.client.list_messages("folder", "bank@example.com", ["账单"], 30,
                                                 since_at=since, include_all=True)
        self.assertEqual(messages, [unrelated])
        self.assertIn("2026-09-25T00:00:00+00:00", get.call_args.kwargs["params"]["$filter"])


if __name__ == "__main__":
    unittest.main()
