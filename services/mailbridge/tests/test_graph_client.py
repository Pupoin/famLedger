import unittest
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

    def test_delta_follows_pages_and_reuses_completion_token(self):
        next_url = "https://graph.microsoft.com/next"
        delta_url = "https://graph.microsoft.com/delta"
        with patch.object(self.client, "_get", side_effect=[
            {"value": [{"id": "one"}], "@odata.nextLink": next_url},
            {"value": [{"id": "two"}], "@odata.deltaLink": delta_url},
            {"value": [], "@odata.deltaLink": delta_url},
        ]) as get:
            self.assertEqual(self.client.delta_messages("folder"), ([{"id": "one"}, {"id": "two"}], delta_url))
            self.assertIsNone(get.call_args.kwargs["params"])
            self.assertEqual(self.client.delta_messages("folder", delta_url), ([], delta_url))
            self.assertEqual(get.call_args.args[0], delta_url)

    def test_initial_delta_does_not_cap_history_with_top(self):
        with patch.object(self.client, "_get", return_value={
            "value": [], "@odata.deltaLink": "https://graph.microsoft.com/delta",
        }) as get:
            self.client.delta_messages("folder")
            self.assertNotIn("$top", get.call_args.kwargs["params"])
            self.assertIn("odata.maxpagesize=100", self.client.session.headers["Prefer"])

    def test_expired_delta_resets_scan(self):
        response = self.response(410)
        error = requests.HTTPError(response=response)
        with patch.object(self.client, "_get", side_effect=[error, {"value": [], "@odata.deltaLink": "https://graph.microsoft.com/new"}]) as get:
            self.assertEqual(self.client.delta_messages("folder", "https://graph.microsoft.com/old")[1], "https://graph.microsoft.com/new")
            self.assertIn("/messages/delta", get.call_args.args[0])

    def test_paging_cannot_leak_bearer_to_external_host(self):
        self.client.session.get = Mock()
        with self.assertRaises(ValueError):
            self.client._get("https://evil.example/messages")
        self.client.session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
