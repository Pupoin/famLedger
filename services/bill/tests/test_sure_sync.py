import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

from backend.ingest.models import TransactionRecord
from backend.ingest.sure_sync import SureClient, classify, external_id, sync_records


def record(**overrides):
    values = dict(
        cost_time=datetime(2026, 9, 25, 12, 34, 56),
        cost=Decimal("-28.50"), account="2238", behaviour="消费",
        business="美团外卖", remain="", source="test",
        original_cost=Decimal("-28.50"), original_currency="CNY",
    )
    values.update(overrides)
    return TransactionRecord(**values)


class FakeResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, *, accounts=None, transactions=None, categories=None, transaction_status=201):
        self.headers = {}
        self.accounts = accounts or []
        self.transactions = transactions or []
        self.categories = categories or []
        self.transaction_status = transaction_status
        self.posts = []

    def request(self, method, url, **kwargs):
        path = url.rsplit("/", 1)[-1]
        if method == "GET":
            key, values = {
                "accounts": ("accounts", self.accounts),
                "transactions": ("transactions", self.transactions),
                "categories": ("categories", self.categories),
            }[path]
            page = kwargs["params"]["page"]
            return FakeResponse({key: values[(page - 1) * 100:page * 100],
                                 "pagination": {"total_pages": max(1, (len(values) + 99) // 100)}})
        self.posts.append((path, kwargs["json"]))
        if path == "categories":
            item = {"id": "new-category", "name": kwargs["json"]["category"]["name"], "parent": None}
            self.categories.append(item)
            return FakeResponse(item, 201)
        item = dict(kwargs["json"]["transaction"])
        item.update(id="new-transaction", occurred_at=item["occurred_at"], amount_cents=2850,
                    classification=item["nature"])
        return FakeResponse(item, self.transaction_status)


class SureSyncTests(unittest.TestCase):
    def client(self, **kwargs):
        session = FakeSession(**kwargs)
        return SureClient("http://sure/api/v1", "test-key", session=session), session

    def test_fingerprint_uses_five_bill_identity_fields(self):
        original = record(business="美团 外卖")
        self.assertEqual(external_id(original), external_id(record(business=" 美团　外卖 ", original_cost=Decimal("-28.500"), original_currency="cny")))
        self.assertNotEqual(external_id(original), external_id(record(account="9085")))
        self.assertNotEqual(external_id(original), external_id(record(original_cost=Decimal("-29"))))
        self.assertNotEqual(
            external_id(original),
            external_id(record(cost_time=datetime(2026, 9, 25, 12, 34, 57))),
        )

    def test_payment_suffix_does_not_duplicate_same_bank_transaction(self):
        self.assertEqual(external_id(record(business="支付宝-商户快捷支付")),
                         external_id(record(business="支付宝-商户快捷")))

    def test_push_exact_payload_and_full_mail(self):
        client, session = self.client(accounts=[{"id": "acct", "name": "2238", "institution_name": "中国招商银行"}],
                                      categories=[{"id": "cat", "name": "🍴 餐饮美食", "parent": None}])
        counts = sync_records([(record(), "完整邮件正文\n第二行")], client=client,
                              institution="中国招商银行", rules=[{"category": "餐饮美食", "patterns": ["美团"]}])
        self.assertEqual(counts["created"], 1)
        payload = [data["transaction"] for path, data in session.posts if path == "transactions"][0]
        self.assertEqual(payload["occurred_at"], "2026-09-25T12:34:56+08:00")
        self.assertEqual(payload["amount"], "28.50")
        self.assertEqual(payload["nature"], "expense")
        self.assertEqual(payload["category_id"], "cat")
        self.assertEqual(payload["notes"], "完整邮件正文\n第二行")
        self.assertEqual(payload["external_id"], external_id(record()))

    def test_incoming_transfer_includes_structured_parties(self):
        client, session = self.client(accounts=[{"id": "acct", "name": "7931", "institution_name": "中国招商银行"}])
        transfer = record(account="7931", cost=Decimal("500"), original_cost=Decimal("500"),
                          behaviour="转入", business="收到本行转入", payer_name="张三",
                          payer_account_last4="9459")
        sync_records([(transfer, "完整邮件")], client=client, institution="中国招商银行", rules=[])
        payload = [data["transaction"] for path, data in session.posts if path == "transactions"][0]
        self.assertEqual(payload["counterparty"], {
            "payer_name": "张三", "payer_account_last4": "9459", "payee_account_last4": "7931",
        })

    def test_known_card_repayment_is_not_regular_spending(self):
        client, session = self.client(accounts=[
            {"id": "source", "name": "6061", "institution_name": "中国招商银行", "account_type": "depository"},
            {"id": "card", "name": "9249", "institution_name": "中国招商银行", "account_type": "credit_card"},
        ])
        payment = record(account="6061", cost=Decimal("-13"), original_cost=Decimal("-13"),
                         behaviour="还款", business="向尾号为9249的信用卡还款",
                         payee_account_last4="9249")
        counts = sync_records([(payment, "完整邮件")], client=client,
                              institution="中国招商银行", rules=[])
        self.assertEqual(counts["created"], 1)
        payload = [data["transaction"] for path, data in session.posts if path == "transactions"][0]
        self.assertEqual(payload["kind"], "cc_payment")
        self.assertEqual(payload["nature"], "expense")
        self.assertEqual(payload["counterparty"]["payee_account_id"], "card")

    def test_transfer_links_only_unique_existing_outflow(self):
        client, _ = self.client()
        incoming_record = record(account="7931", cost=Decimal("500"), original_cost=Decimal("500"),
                                 behaviour="转入", business="收到本行转入", payer_name="张三",
                                 payer_account_last4="9459")
        client.account_for = Mock(side_effect=[{"id": "recipient"}, {"id": "payer"}])
        client.existing_entry_for = Mock(return_value={"id": "incoming", "counterparty": None, "transfer": None})
        client.day_transactions = Mock(return_value=[{
            "id": "outgoing", "amount_cents": 50000, "classification": "expense",
            "kind": "standard", "transfer": None, "name": "转账汇款",
        }])
        client.request = Mock(return_value={"id": "transfer-id"})

        self.assertEqual(client.match_bank_transfer(incoming_record, "中国招商银行"), "linked")
        self.assertEqual(client.request.call_args_list[-1].args, ("POST", "transfers"))
        self.assertEqual(client.request.call_args_list[-1].kwargs["payload"]["transfer"], {
            "outflow_transaction_id": "outgoing", "inflow_transaction_id": "incoming",
        })
        client.request.reset_mock()
        client.account_for.side_effect = [{"id": "recipient"}, {"id": "payer"}]
        self.assertEqual(client.match_bank_transfer(incoming_record, "中国招商银行", dry_run=True), "would_link")
        client.request.assert_not_called()

    def test_unknown_payer_records_metadata_but_does_not_link(self):
        client, _ = self.client()
        incoming_record = record(account="7931", cost=Decimal("500"), original_cost=Decimal("500"),
                                 behaviour="转入", business="收到本行转入", payer_account_last4="9459")
        client.account_for = Mock(side_effect=[{"id": "recipient"}, None])
        client.existing_entry_for = Mock(return_value={"id": "incoming", "counterparty": None, "transfer": None})
        client.request = Mock(return_value={"id": "incoming"})

        self.assertEqual(client.match_bank_transfer(incoming_record, "中国招商银行"), "unmatched_account")
        client.request.assert_not_called()

    def test_unique_accounts_infer_missing_outflow(self):
        client, _ = self.client()
        incoming_record = record(account="7931", cost=Decimal("500"), original_cost=Decimal("500"),
                                 behaviour="转入", business="收到本行转入", payer_account_last4="9459")
        client.account_for = Mock(side_effect=[{"id": "recipient"}, {"id": "payer"}])
        client.existing_entry_for = Mock(return_value={"id": "incoming", "kind": "standard", "transfer": None})
        client.day_transactions = Mock(return_value=[])
        client.request = Mock(return_value={"id": "incoming"})

        self.assertEqual(client.match_bank_transfer(incoming_record, "中国招商银行"), "inferred")
        self.assertEqual(client.request.call_args_list[0].args, ("PATCH", "transactions/incoming"))
        self.assertEqual(client.request.call_args_list[0].kwargs["payload"], {"transaction": {
            "counterparty": {
                "payer_account_last4": "9459", "payer_account_id": "payer", "payee_account_last4": "7931",
            },
        }})
        self.assertEqual(client.request.call_args_list[1].args, ("POST", "transfers"))
        self.assertEqual(client.request.call_args_list[1].kwargs["payload"]["transfer"], {
            "source_account_id": "payer", "inflow_transaction_id": "incoming",
        })
        client.request.reset_mock()
        client.account_for.side_effect = [{"id": "recipient"}, {"id": "payer"}]
        self.assertEqual(client.match_bank_transfer(incoming_record, "中国招商银行", dry_run=True), "would_infer")
        client.request.assert_not_called()

    def test_possible_real_outflow_without_transfer_name_blocks_inference(self):
        client, _ = self.client()
        incoming_record = record(account="7931", cost=Decimal("500"), original_cost=Decimal("500"),
                                 behaviour="转入", business="收到本行转入", payer_account_last4="9459")
        client.account_for = Mock(side_effect=[{"id": "recipient"}, {"id": "payer"}])
        client.existing_entry_for = Mock(return_value={"id": "incoming", "kind": "funds_movement", "transfer": None})
        client.day_transactions = Mock(return_value=[{
            "id": "other-outflow", "amount_cents": 50000, "classification": "expense",
            "kind": "standard", "transfer": None, "name": "银联扣款",
        }])
        client.request = Mock()

        self.assertEqual(client.match_bank_transfer(incoming_record, "中国招商银行"), "ambiguous")
        client.request.assert_not_called()

    def test_historical_match_and_ambiguous_match_do_not_post(self):
        old = {"occurred_at": "2026-09-25T04:34:56Z", "amount_cents": 2850,
               "name": "美团外卖", "classification": "expense", "external_id": None}
        client, session = self.client(accounts=[{"id": "acct", "name": "2238", "institution_name": "中国招商银行"}],
                                      transactions=[old])
        counts = sync_records([(record(), "body")], client=client,
                              institution="中国招商银行", rules=[])
        self.assertEqual(counts["duplicate"], 1)
        self.assertFalse(session.posts)
        client2, session2 = self.client(accounts=[{"id": "acct", "name": "2238", "institution_name": "中国招商银行"}],
                                        transactions=[old, old])
        counts = sync_records([(record(), "body")], client=client2,
                              institution="中国招商银行", rules=[])
        self.assertEqual(counts["ambiguous"], 1)
        self.assertFalse(session2.posts)

    def test_account_mismatch_never_creates_category_or_transaction(self):
        client, session = self.client(accounts=[{"id": "acct", "name": "2238", "institution_name": "别的银行"}])
        counts = sync_records([(record(), "body")], client=client,
                              institution="中国招商银行", rules=[])
        self.assertEqual(counts["unmatched_account"], 1)
        self.assertFalse(session.posts)

    def test_missing_category_is_created(self):
        client, session = self.client(accounts=[{"id": "acct", "name": "2238", "institution_name": "中国招商银行"}])
        counts = sync_records([(record(), "body")], client=client,
                              institution="中国招商银行", rules=[{"category": "餐饮美食", "patterns": ["美团"]}])
        self.assertEqual(counts["created"], 1)
        self.assertEqual([path for path, _ in session.posts], ["categories", "transactions"])

    def test_server_idempotency_hit_counts_as_duplicate(self):
        client, _ = self.client(accounts=[{"id": "acct", "name": "2238", "institution_name": "中国招商银行"}],
                                categories=[{"id": "cat", "name": "餐饮美食", "parent": None}],
                                transaction_status=200)
        counts = sync_records([(record(), "body")], client=client,
                              institution="中国招商银行", rules=[{"category": "餐饮美食", "patterns": ["美团"]}])
        self.assertEqual(counts["duplicate"], 1)
        self.assertEqual(counts["created"], 0)


if __name__ == "__main__":
    unittest.main()
