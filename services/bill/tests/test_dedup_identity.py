import os
import unittest
from datetime import datetime
from decimal import Decimal

import psycopg

from backend.ingest.db import backfill_transfer_parties, ensure_bill_table, insert_transaction_if_new
from backend.ingest.models import TransactionRecord


class TransactionIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        dsn = os.environ.get("BILL_TEST_POSTGRES_DSN")
        if not dsn:
            raise unittest.SkipTest("BILL_TEST_POSTGRES_DSN is required for database tests")

        cls.conn = psycopg.connect(dsn, autocommit=True)
        if not cls.conn.info.dbname.endswith("_test"):
            cls.conn.close()
            raise RuntimeError("Refusing to run identity tests outside a *_test database")

        with cls.conn.transaction():
            ensure_bill_table(cls.conn)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def setUp(self) -> None:
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.execute('TRUNCATE TABLE "CMB_bill" RESTART IDENTITY')

    def record(self, *, account="2238", business="美团 外卖", currency="CNY", amount="-28.50", minute=0):
        return TransactionRecord(
            cost_time=datetime(2026, 9, 25, 12, minute),
            cost=Decimal(amount),
            account=account,
            behaviour="消费",
            business=business,
            remain="",
            source="test",
            original_cost=Decimal(amount),
            original_currency=currency,
        )

    def test_five_part_identity(self) -> None:
        with self.conn.transaction():
            self.assertTrue(insert_transaction_if_new(self.conn, self.record(), ensure_table=False, auto_commit=False))
            self.assertFalse(insert_transaction_if_new(self.conn, self.record(business="  美团　外卖  "), ensure_table=False, auto_commit=False))
            self.assertFalse(insert_transaction_if_new(self.conn, self.record(account=" 2238 "), ensure_table=False, auto_commit=False))
            self.assertTrue(insert_transaction_if_new(self.conn, self.record(account="9085"), ensure_table=False, auto_commit=False))
            self.assertTrue(insert_transaction_if_new(self.conn, self.record(business="饿了么 外卖"), ensure_table=False, auto_commit=False))
            self.assertTrue(insert_transaction_if_new(self.conn, self.record(minute=1), ensure_table=False, auto_commit=False))
            self.assertTrue(insert_transaction_if_new(self.conn, self.record(amount="-29.50"), ensure_table=False, auto_commit=False))
            self.assertTrue(insert_transaction_if_new(self.conn, self.record(currency="USD"), ensure_table=False, auto_commit=False))
            self.assertFalse(insert_transaction_if_new(self.conn, self.record(currency="usd"), ensure_table=False, auto_commit=False))

        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "CMB_bill"')
            self.assertEqual(cur.fetchone()[0], 6)

    def test_duplicate_email_enriches_parties_without_new_transaction(self) -> None:
        first = self.record()
        second = self.record()
        second.payer_name = "张三"
        second.payer_account_last4 = "9459"
        with self.conn.transaction():
            self.assertTrue(insert_transaction_if_new(self.conn, first, ensure_table=False, auto_commit=False, mail_body="原邮件"))
            self.assertFalse(insert_transaction_if_new(self.conn, second, ensure_table=False, auto_commit=False, mail_body="原邮件"))
        with self.conn.cursor() as cur:
            cur.execute('SELECT count(*), max(payer_account_last4) FROM "CMB_bill"')
            self.assertEqual(cur.fetchone(), (1, "9459"))

    def test_stored_mail_backfills_payer(self) -> None:
        first = self.record(account="7931", business="收到本行转入", amount="500")
        first.behaviour = "转入"
        body = "您账户7931于08月22日收到本行转入人民币500.00，余额543.78，付方张三（9459），备注：转账"
        with self.conn.transaction():
            self.assertTrue(insert_transaction_if_new(self.conn, first, ensure_table=False, auto_commit=False, mail_body=body))
            self.assertEqual(backfill_transfer_parties(self.conn), 1)
        with self.conn.cursor() as cur:
            cur.execute('SELECT payer_name, payer_account_last4 FROM "CMB_bill"')
            self.assertEqual(cur.fetchone(), ("张三", "9459"))

    def test_manual_insert_uses_same_identity(self) -> None:
        with self.conn.transaction():
            insert_transaction_if_new(self.conn, self.record(), ensure_table=False, auto_commit=False)

        with self.assertRaises(psycopg.errors.UniqueViolation):
            with self.conn.transaction():
                with self.conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO "CMB_bill" (costtime, cost, original_cost, original_currency, account, business)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (datetime(2026, 9, 25, 12), -28.50, -28.50, "cny", "2238", "美团  外卖"))


if __name__ == "__main__":
    unittest.main()
