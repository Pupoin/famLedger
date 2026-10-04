#!/usr/bin/env python3
"""Append exactly 1,000 linked demo transactions for one existing user.

Existing data and preferences are preserved. Quotes are genuine historical
quotes; invented transactions and bank settlements are explicitly marked.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import random
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import requests
from sqlalchemy import func, text
from sqlmodel import Session, select
from database import engine
from models import Account, Category, ExchangeRateSnapshot, Family, RefundAllocation, Tag, Transaction, TransactionSplit, Transfer, User
from services.booking_money import assign_booking, money, money_text, prepare_booking
from services.data_integrity import sqlite_integrity_problems
from services.refund_money import allocate
from services.report_currency import _valid_rates
from services.transaction_lock import lock_mutation

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
NEEDED = {"EUR", "USD", "CNY", "JPY", "HKD", "GBP", "AUD"}


def historical_quotes(days):
    """Fetch missing dates concurrently, then persist real quotes in one write."""
    saved = {}
    with Session(engine) as session:
        for day in days:
            row = session.get(ExchangeRateSnapshot, (day, "EUR"))
            if row:
                rates = _valid_rates(row.rates)
                if not NEEDED <= rates.keys() or not 0 <= (day - row.effective_date).days <= 7:
                    raise RuntimeError(f"Invalid existing quote for {day}")
                saved[day] = (rates, row.effective_date)

    def fetch(day):
        for attempt in range(3):
            try:
                response = requests.get(f"https://api.frankfurter.app/{day.isoformat()}", params={"from": "EUR"}, timeout=12)
                response.raise_for_status()
                data = response.json()
                rates, effective = _valid_rates(data["rates"]), date.fromisoformat(data["date"])
                if data.get("base") != "EUR" or not NEEDED <= rates.keys() or not 0 <= (day - effective).days <= 7:
                    raise ValueError("Invalid historical quote response")
                return rates, effective
            except (requests.RequestException, ValueError, KeyError):
                if attempt == 2:
                    raise

    missing = [day for day in days if day not in saved]
    print(f"Historical FX: {len(saved)} dates cached, {len(missing)} dates to fetch", flush=True)
    fetched = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(fetch, day): day for day in missing}
        for future in as_completed(jobs):
            day = jobs[future]
            fetched[day] = future.result()
            if len(fetched) % 10 == 0 or len(fetched) == len(missing):
                print(f"Historical FX fetched: {len(fetched)}/{len(missing)}", flush=True)
    with Session(engine) as session:
        lock_mutation(session)
        for day, (rates, effective) in fetched.items():
            if not session.get(ExchangeRateSnapshot, (day, "EUR")):
                session.add(ExchangeRateSnapshot(requested_date=day, effective_date=effective, base_currency="EUR",
                                                rates={code: str(value) for code, value in rates.items()}, provider="frankfurter"))
        session.commit()
    saved.update(fetched)
    return saved


def generate(username, end_day):
    if engine.dialect.name != "sqlite" or not Path(engine.url.database).resolve().is_relative_to(ROOT):
        raise RuntimeError("This development seeder only operates on the database inside this project")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise ValueError("Invalid username")
    start = end_day - timedelta(days=89)
    if end_day > datetime.now(LOCAL_TZ).date() - timedelta(days=1):
        raise ValueError("Use completed historical days, without future transactions")
    batch = f"demo-{username}-90d-{end_day.isoformat()}-v1"
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).one_or_none()
        if not user or not user.is_active or not user.family_id:
            raise RuntimeError("The target must be an active existing user with a family")
        family = session.get(Family, user.family_id)
        if not family or family.status != "active":
            raise RuntimeError("The target family must be active")
        account_ids = session.exec(select(Account.id).where(Account.owner_id == user.id)).all()
        existing = session.exec(select(func.count()).select_from(Transaction).where(
            Transaction.account_id.in_(account_ids), Transaction.external_id.startswith(batch + ":"))).one()
        if existing:
            if existing != 1000:
                raise RuntimeError(f"Existing incomplete batch has {existing} rows; no data was deleted")
            print(f"Batch already contains 1000 rows: {batch}; no duplicate import", flush=True)
            return None

    quotes = historical_quotes([start + timedelta(days=i) for i in range(90)])
    rng = random.Random(20261003)
    scenarios = Counter()
    created = []
    with Session(engine) as session:
        lock_mutation(session)
        user = session.exec(select(User).where(User.username == username)).one()
        family = session.get(Family, user.family_id)
        if not user.is_active or family.status != "active":
            raise RuntimeError("User or family changed while fetching quotes")
        if session.exec(select(Transaction.id).where(Transaction.external_id.startswith(batch + ":"))).first():
            raise RuntimeError("Another importer created this batch; no duplicate import")
        before_total = session.exec(select(func.count()).select_from(Transaction)).one()
        old_integrity = sqlite_integrity_problems(session.connection().connection.driver_connection)
        specs = [
            ("bank", "人民币借记卡", "CNY", "checking", "asset", "招商银行", "50000"),
            ("savings", "人民币储蓄", "CNY", "savings", "asset", "建设银行", "100000"),
            ("wallet", "零钱钱包", "CNY", "cash", "asset", "移动支付", "3000"),
            ("usd", "美元账户", "USD", "checking", "asset", "海外银行", "12000"),
            ("eur", "欧元账户", "EUR", "checking", "asset", "欧洲银行", "10000"),
            ("credit", "人民币信用卡主卡", "CNY", "credit_card", "liability", "招商银行", "500"),
            ("usd_credit", "美元信用卡", "USD", "credit_card", "liability", "海外银行", "100"),
            ("subcard", "美元副卡", "USD", "credit_card", "liability", "海外银行", "30"),
        ]
        accounts = {}
        for key, name, code, kind, classification, institution, _ in specs:
            account = Account(owner_id=user.id, family_id=user.family_id, name=f"模拟·{name}", currency=code,
                              account_type=kind, classification=classification, institution_name=institution,
                              external_identifier=f"{batch}:{key}", balance=Decimal(0))
            if key == "subcard":
                account.parent_account_id = accounts["credit"].id
            session.add(account)
            session.flush()
            accounts[key] = account

        expense_names = ["餐饮美食", "超市便利", "交通出行", "购物消费", "生活缴费", "医疗健康", "娱乐休闲", "旅行住宿", "教育学习", "数码订阅", "宠物用品", "其他"]
        income_names = ["工资薪酬", "奖金补贴", "兼职副业", "理财收益", "公费报销收入", "其他收入"]
        categories = {}
        for kind, names in (("expense", expense_names), ("income", income_names)):
            for name in names:
                category = session.exec(select(Category).where(Category.family_id == user.family_id,
                    Category.name == name, Category.category_type == kind, Category.parent_id.is_(None))).first()
                if not category:
                    category = Category(family_id=user.family_id, name=name, category_type=kind,
                                        icon="💰" if kind == "income" else "🛍️")
                    session.add(category); session.flush()
                categories[name] = category
        tag_ids = {}
        for name in ["模拟数据", "外币消费", "日常消费", "信用卡还款", "退款", "账单拆分", "公费报销"]:
            tag = session.exec(select(Tag).where(Tag.family_id == user.family_id, Tag.name == name)).first()
            if not tag:
                tag = Tag(family_id=user.family_id, name=name, color="#6366f1")
                session.add(tag); session.flush()
            tag_ids[name] = str(tag.id)

        def add(account, day, amount, native, narration, kind="expense", category=None, scenario="消费", bank_amount=None, extra=None, tags=()):
            original = money(amount, positive=True)
            rates, _ = quotes[day]
            spread = Decimal(rng.choice(["0.998", "1", "1.002", "1.005"])) if native != account.currency else Decimal(1)
            booked = money(bank_amount if bank_amount is not None else original * rates[account.currency] / rates[native] * spread, positive=True)
            parent = accounts["credit"] if account.parent_account_id else None
            master_amount = money(booked * rates[parent.currency] / rates[account.currency]) if parent else None
            fields = prepare_booking(session, account, amount=original, original_currency=native, day=day,
                                     settlement_amount=booked, settlement_currency=account.currency,
                                     master_settlement_amount=master_amount, master_settlement_currency=parent.currency if parent else None,
                                     source_name="模拟银行结算")
            moment = datetime(day.year, day.month, day.day, rng.randint(9, 21), rng.randrange(60), rng.randrange(60), tzinfo=LOCAL_TZ).astimezone(timezone.utc)
            row = Transaction(account_id=account.id, external_id=f"{batch}:{len(created) + 1:04d}",
                              transacted_at=day, occurred_at=moment, created_at=moment, updated_at=moment,
                              narration=f"{narration} · 模拟{len(created) + 1:04d}", amount=booked, currency=account.currency,
                              category_id=categories[category].id if category else None, transaction_type=kind,
                              category_source="manual", merchant_source="manual",
                              notes="人工生成的演示流水，非真实账单；银行结算为模拟金额，历史市场汇率来自真实缓存。",
                              extra={"demo_batch": batch, "demo_scenario": scenario, **(extra or {})},
                              tags=[tag_ids["模拟数据"], *(tag_ids[name] for name in tags)])
            assign_booking(row, fields)
            session.add(row); session.flush()
            created.append(row)
            scenarios[scenario] += 1
            return row

        for key, _, code, _, classification, _, opening in specs:
            row = add(accounts[key], start, opening, code, "期初欠款" if classification == "liability" else "期初余额",
                      kind="expense" if classification == "liability" else "income", scenario="期初", extra={"is_initial": True, "source": "account_opening"})
            row.excluded_from_stats = True

        merchants = [
            ("瑞幸咖啡", "餐饮美食", "CNY", 12, 45), ("盒马鲜生", "超市便利", "CNY", 35, 450),
            ("滴滴出行", "交通出行", "CNY", 15, 180), ("京东自营", "购物消费", "CNY", 50, 3500),
            ("电费燃气费", "生活缴费", "CNY", 65, 400), ("医院门诊", "医疗健康", "CNY", 80, 650),
            ("周末电影", "娱乐休闲", "CNY", 40, 220), ("高铁酒店", "旅行住宿", "CNY", 180, 1800),
            ("在线课程", "教育学习", "CNY", 120, 900), ("宠物用品", "宠物用品", "CNY", 35, 360),
            ("纽约咖啡店", "餐饮美食", "USD", 8, 35), ("Amazon 美国站", "购物消费", "USD", 25, 450),
            ("Netflix 订阅", "数码订阅", "USD", 12, 25), ("巴黎咖啡与面包", "餐饮美食", "EUR", 6, 35),
            ("柏林书店", "教育学习", "EUR", 15, 120), ("东京药妆店", "购物消费", "JPY", 1500, 18000),
            ("大阪拉面店", "餐饮美食", "JPY", 700, 1800), ("香港茶餐厅", "餐饮美食", "HKD", 45, 180),
            ("伦敦博物馆商店", "娱乐休闲", "GBP", 10, 90), ("悉尼超市", "超市便利", "AUD", 18, 160),
        ]
        expenses = []
        for i in range(642):
            day = start + timedelta(days=i * 90 // 642)
            name, category, native, low, high = rng.choice(merchants)
            keys = ["bank", "wallet", "credit", "subcard"] if native == "CNY" else ["usd", "usd_credit", "subcard", "credit", "eur"]
            value = Decimal(rng.randint(low * 100, high * 100)) / 100
            row = add(accounts[rng.choice(keys)], day, value, native, name, category=category,
                      tags=["日常消费"] + (["外币消费"] if native != "CNY" else []))
            if i % 16 == 0:
                row.is_reimbursable = True
                row.reimbursement_status = rng.choice(["unclaimed", "claimed", "settled"])
                row.extra = {**row.extra, "reimbursement_type": "corporate", "counterparty": "模拟科技公司"}
                row.tags = [*row.tags, tag_ids["公费报销"]]
            expenses.append(row)

        for i in range(50):
            day = start + timedelta(days=(i * 13 + 4) % 90)
            category = income_names[i % len(income_names)]
            key = rng.choice(["bank", "usd", "eur"])
            value = rng.randint(18000, 32000) if category == "工资薪酬" else rng.randint(100, 3500)
            add(accounts[key], day, value, "CNY", f"模拟公司·{category}", kind="income", category=category, scenario="收入")

        refundable = [t for t in expenses if t.transacted_at <= end_day - timedelta(days=15)]
        rng.shuffle(refundable)
        used = set()
        for i in range(80):
            if i >= 70:
                groups = defaultdict(list)
                for t in refundable:
                    if t.id not in used:
                        groups[(t.account_id, t.original_currency)].append(t)
                originals = next(rows[:2] for rows in groups.values() if len(rows) >= 2)
                quantities = [money(t.original_amount * Decimal("0.4")) for t in originals]
                scenario = "多笔消费合并退款"
            else:
                originals = [next(t for t in refundable if t.id not in used)]
                quantities = [money(originals[0].original_amount * (Decimal(1) if i < 40 else Decimal("0.35")))]
                scenario = "全额退款" if i < 40 else "部分退款"
            used.update(t.id for t in originals)
            original = originals[0]
            day = max(t.transacted_at for t in originals) + timedelta(days=rng.randint(2, 12))
            actual = money(sum((t.amount * q / t.original_amount for t, q in zip(originals, quantities)), Decimal(0)) * (Decimal("1.02") if i % 2 == 0 else Decimal("0.98")))
            account = next(a for a in accounts.values() if a.id == original.account_id)
            refund = add(account, day, sum(quantities), original.original_currency, f"{scenario}·退货到账", kind="refund",
                         category=next(name for name, cat in categories.items() if cat.id == original.category_id),
                         scenario=scenario, bank_amount=actual, tags=["退款"])
            for prior, quantity in zip(originals, quantities):
                allocate(session, user, refund, prior, quantity=quantity)

        for i in range(100):
            day = start + timedelta(days=(i * 7 + 10) % 90)
            repayment = i >= 60
            if repayment:
                source, destination = (accounts["bank"], accounts["credit"]) if i % 2 == 0 else (accounts["usd"], accounts["usd_credit"])
                value = Decimal(rng.randint(100, 1400) if source.currency == "CNY" else rng.randint(20, 180))
                scenario = "信用卡还款"
            else:
                source, destination = rng.sample([accounts["bank"], accounts["savings"], accounts["wallet"]], 2)
                value, scenario = Decimal(rng.randint(50, 2500)), "内部转账"
            outflow = add(source, day, value, source.currency, f"{scenario}转出·至{destination.name}", kind="transfer",
                          scenario=scenario, extra={"direction": "outflow"}, tags=["信用卡还款"] if repayment else [])
            inflow = add(destination, day, value, destination.currency, f"{scenario}转入·来自{source.name}", kind="transfer",
                         scenario=scenario, extra={"direction": "inflow"}, tags=["信用卡还款"] if repayment else [])
            inflow.occurred_at = outflow.occurred_at + timedelta(seconds=2)
            pair = Transfer(family_id=user.family_id, outflow_transaction_id=outflow.id, inflow_transaction_id=inflow.id, amount=value, status="confirmed")
            session.add(pair); session.flush()
            outflow.transfer_id = inflow.transfer_id = pair.id
            session.add_all([outflow, inflow])

        for i in range(20):
            account = rng.choice(list(accounts.values()))
            direction = "decrease" if i % 2 else "increase"
            add(account, start + timedelta(days=(i * 11) % 90), Decimal(rng.randint(100, 8000)) / 100,
                account.currency, "余额对账·减少" if direction == "decrease" else "余额对账·增加", kind="adjustment",
                scenario="对账调整", extra={"direction": direction})

        split_expenses = [t for t in expenses if t.id not in used][:40]
        for row in split_expenses:
            first, second = money(row.amount * Decimal("0.5")), money(row.amount * Decimal("0.3"))
            row.is_split = True
            row.tags = [*row.tags, tag_ids["账单拆分"]]
            for amount, category in zip([first, second, row.amount - first - second], ["超市便利", "生活缴费", "购物消费"]):
                session.add(TransactionSplit(transaction_id=row.id, category_id=categories[category].id, amount=amount, notes="模拟账单分类拆分"))
        session.flush()
        if len(created) != 1000 or session.exec(select(func.count()).select_from(Transaction)).one() != before_total + 1000:
            raise RuntimeError("The batch must add exactly 1000 rows")
        # Validate every new relationship directly. Old invalid rows belonging
        # to other users must neither be deleted nor hide an invalid new row.
        by_id = {t.id: t for t in created}
        account_by_id = {a.id: a for a in accounts.values()}
        for row in created:
            account = account_by_id[row.account_id]
            assert account.owner_id == user.id and account.family_id == user.family_id
            assert row.currency == account.currency and row.original_amount > 0 and row.exchange_rate > 0
            assert abs(money(row.original_amount * row.exchange_rate) - row.amount) <= Decimal("0.0001")
            if account.parent_account_id:
                assert row.master_account_id == account.parent_account_id and row.master_settlement_amount > 0
                assert row.master_settlement_currency == account_by_id[account.parent_account_id].currency
        pairs = session.exec(select(Transfer).where(Transfer.outflow_transaction_id.in_(by_id))).all()
        assert len(pairs) == 100
        for pair in pairs:
            outgoing, incoming = by_id[pair.outflow_transaction_id], by_id[pair.inflow_transaction_id]
            assert pair.family_id == user.family_id and outgoing.currency == incoming.currency
            assert pair.amount == outgoing.amount == incoming.amount
            assert outgoing.transfer_id == incoming.transfer_id == pair.id
            assert outgoing.extra['direction'] == 'outflow' and incoming.extra['direction'] == 'inflow'
        refund_ids = [t.id for t in created if t.transaction_type == 'refund']
        allocations = session.exec(select(RefundAllocation).where(RefundAllocation.refund_transaction_id.in_(refund_ids))).all()
        assert len(allocations) == 90
        original_used, refund_used = defaultdict(Decimal), defaultdict(Decimal)
        for link in allocations:
            original, linked_refund = by_id[link.original_transaction_id], by_id[link.refund_transaction_id]
            assert original.transaction_type == 'expense' and linked_refund.transaction_type == 'refund'
            assert link.original_currency == original.original_currency == linked_refund.original_currency
            assert link.allocated_amount > 0 and link.refund_original_amount == link.allocated_amount
            assert link.original_book_currency == original.currency and link.refund_book_currency == linked_refund.currency
            assert link.original_book_amount >= 0 and link.refund_book_amount >= 0
            original_used[original.id] += link.allocated_amount
            refund_used[linked_refund.id] += link.refund_original_amount
        assert all(value <= by_id[key].original_amount for key, value in original_used.items())
        assert all(refund_used[key] == by_id[key].original_amount for key in refund_ids)
        splits = session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(by_id))).all()
        split_totals = defaultdict(Decimal)
        for part in splits:
            assert part.amount > 0 and session.get(Category, part.category_id).family_id == user.family_id
            split_totals[part.transaction_id] += part.amount
        assert len(split_totals) == 40 and all(value == by_id[key].amount for key, value in split_totals.items())
        problems = sqlite_integrity_problems(session.connection().connection.driver_connection)
        if set(problems) - set(old_integrity):
            raise RuntimeError("Integrity validation failed; import rolled back: " + "; ".join(problems))
        summary = {
            "username": username, "batch": batch, "date_start": start.isoformat(), "date_end": end_day.isoformat(),
            "transaction_count": len(created), "scenarios": dict(scenarios),
            "original_currencies": dict(Counter(t.original_currency for t in created)),
            "foreign_booking_count": sum(t.original_currency != t.currency for t in created),
            "master_settlement_count": sum(t.master_account_id is not None for t in created),
            "transfer_pairs": 100, "refund_rows": 80, "refund_allocations": 90, "split_transactions": len(split_expenses),
            "accounts": [{"id": str(a.id), "name": a.name, "currency": a.currency} for a in accounts.values()],
            "example_expense_id": str(next(t.id for t in expenses if t.original_currency != t.currency)),
            "example_refund_id": str(refund.id), "example_transfer_id": str(outflow.id),
            "historical_fx_dates": len(quotes), "existing_data_preserved": True,
            "new_batch_integrity": "passed", "preexisting_global_integrity_problems": old_integrity,
        }
        session.commit()
    from services.audit import audit_logger
    audit_logger.log("seed_demo_transactions", username, summary)
    output_dir = ROOT / ".cache" / "demo-data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{batch}.json"
    output_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"Summary: {output_file}", flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="jj")
    parser.add_argument("--end-date", type=date.fromisoformat, default=datetime.now(LOCAL_TZ).date() - timedelta(days=1))
    args = parser.parse_args()
    generate(args.username, args.end_date)
