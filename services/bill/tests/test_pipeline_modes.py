import os
import unittest
from contextlib import ExitStack
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.ingest import pipeline
from backend.ingest.models import TransactionRecord


class PipelineModesTests(unittest.TestCase):
    def test_without_email_cache_all_parsers_and_db_to_sure_sync_still_run(self):
        def message(identifier, cached=False):
            result = {
                "id": identifier, "subject": identifier,
                "receivedDateTime": "2026-09-25T04:00:00Z",
                "body": {"content": "完整邮件正文"},
            }
            if cached:
                result["_bill_email_id"] = 42
            return result

        def record(name):
            return TransactionRecord(
                cost_time=datetime(2026, 9, 25, 12), cost=Decimal("-1.00"),
                account="6061", behaviour="支付", business=name, remain="0",
                source="test", original_cost=Decimal("-1.00"), original_currency="CNY",
            )

        cfg = SimpleNamespace(pg_dsn="test", tenant_id="tenant", client_id="client",
                              graph_scopes=(), token_cache_path="cache", user_id="me",
                              credit_folder_name="credit", debit_folder_name="debit",
                              lookback_days_credit=30, lookback_days_debit=30,
                              one_drive_icon="")
        conn = MagicMock()
        conn.__enter__.return_value = conn
        graph = MagicMock()
        graph.get_folder_id_by_name.side_effect = ["credit-id", "debit-id"]
        graph.list_messages.side_effect = [
            [message("daily")], [message("recent")], [message("debit")],
        ]
        stats = SimpleNamespace(**{key: 0 for key in (
            "month_debit_income", "month_debit_outcome", "month_credit_income",
            "month_credit_outcome", "month_income", "month_outcome",
        )})

        with ExitStack() as stack, patch.dict(os.environ, {"SAVE_EMAILS": "false"}):
            def stub(name, **kwargs):
                return stack.enter_context(patch.object(pipeline, name, **kwargs))

            stub("load_config", return_value=cfg)
            stub("get_connection", return_value=conn)
            stub("ensure_bill_table")
            stub("last_successful_scan_at", return_value=None)
            stub("acquire_graph_token", return_value="token")
            stub("GraphMailClient", return_value=graph)
            store = stub("store_emails")
            stub("fetch_unprocessed_emails", return_value={
                "credit_daily": [], "credit_recent": [], "debit": [message("cached", True)],
                "other": [],
            })
            daily = stub("parse_credit_daily_message", return_value=([record("daily")], None))
            recent = stub("parse_credit_recent_message", return_value=[record("recent")])
            debit = stub("parse_debit_message", side_effect=[record("debit"), record("cached")])
            stub("cleanup_utc_shifted_debit_duplicates", return_value=0)
            insert = stub("insert_transaction_if_new", return_value=True)
            mark = stub("mark_emails_processed")
            stub("save_successful_scan_at")
            stub("fetch_records_in_range", return_value=[])
            stub("fetch_latest_balance", return_value=Decimal("0"))
            stub("build_stats", return_value=stats)
            stub("send_windows_notification")
            sync = stub("sync_pending_from_db")

            pipeline.run()

        self.assertEqual(graph.list_messages.call_count, 3)
        self.assertEqual(daily.call_count, 1)
        self.assertEqual(recent.call_count, 1)
        self.assertEqual(debit.call_count, 2)
        self.assertEqual(insert.call_count, 4)
        self.assertEqual(insert.call_args.kwargs["mail_body"], "完整邮件正文")
        mark.assert_called_once_with(conn, [42])
        sync.assert_called_once_with(conn)
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
