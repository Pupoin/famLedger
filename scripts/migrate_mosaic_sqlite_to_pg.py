#!/usr/bin/env python3
"""Migrate legacy SQLite database (mosaic.db) to famLedger schema (PostgreSQL or SQLite).

Usage:
    python scripts/migrate_mosaic_sqlite_to_pg.py --source-db path/to/mosaic.db --target-db postgresql://famledger:secret@localhost:5432/famledger
"""

import argparse
import logging
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional

from sqlmodel import Session, create_engine, select

# Adjust path to import famledger backend models
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from models import (
    Account,
    Category,
    Family,
    Transaction,
    User,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration")


def migrate(source_db_path: Path, target_db_url: str):
    if not source_db_path.exists():
        logger.error("Source database does not exist: %s", source_db_path)
        sys.exit(1)

    logger.info("Connecting to source SQLite: %s", source_db_path)
    src_conn = sqlite3.connect(str(source_db_path))
    src_conn.row_factory = sqlite3.Row
    src_cur = src_conn.cursor()

    logger.info("Connecting to target database: %s", target_db_url)
    engine = create_engine(target_db_url)

    with Session(engine) as session:
        # 1. 创建或获取默认家庭 (Family)
        family = session.exec(select(Family)).first()
        if not family:
            family = Family(name="我的家庭", currency="CNY")
            session.add(family)
            session.commit()
            session.refresh(family)
            logger.info("Created default family: id=%s", family.id)
        else:
            logger.info("Using existing family: id=%s", family.id)

        # 2. 读取并迁移 User
        user_map: Dict[str, User] = {}
        account_map: Dict[str, Account] = {}

        try:
            src_cur.execute("SELECT * FROM user")
            old_users = src_cur.fetchall()
        except sqlite3.OperationalError:
            old_users = []

        for idx, u in enumerate(old_users):
            username = u["username"]
            display_name = u["display_name"] or username
            email = f"{username}@family.local"

            user = session.exec(select(User).where(User.username == username)).first()
            if not user:
                user = User(
                    family_id=family.id,
                    email=email,
                    username=username,
                    display_name=display_name,
                    password_hash=u["password_hash"] if "password_hash" in u.keys() else None,
                    role="owner" if idx == 0 else "member",
                )
                session.add(user)
                session.commit()
                session.refresh(user)
                logger.info("Migrated user: %s (id=%s)", username, user.id)

            user_map[display_name] = user
            user_map[username] = user

            # 为该用户创建默认活期账户
            acc = session.exec(
                select(Account).where(Account.family_id == family.id, Account.name == f"{display_name}的主账户")
            ).first()
            if not acc:
                acc = Account(
                    family_id=family.id,
                    owner_id=user.id,
                    name=f"{display_name}的主账户",
                    account_type="checking",
                    classification="asset",
                    currency=family.currency,
                    balance=Decimal("0.00"),
                )
                session.add(acc)
                session.commit()
                session.refresh(acc)
                logger.info("Created default account for user: %s", acc.name)
            account_map[display_name] = acc
            account_map[username] = acc

        # 默认主账户 fallback
        default_account = next(iter(account_map.values()), None)
        if not default_account:
            default_account = Account(
                family_id=family.id,
                name="家庭主账户",
                account_type="checking",
                classification="asset",
                currency=family.currency,
                balance=Decimal("0.00"),
            )
            session.add(default_account)
            session.commit()
            session.refresh(default_account)

        # 3. 迁移分类 Categories
        category_map: Dict[str, Category] = {}
        try:
            src_cur.execute("SELECT DISTINCT category FROM expense WHERE category IS NOT NULL")
            categories = src_cur.fetchall()
            for r in categories:
                cname = r["category"].strip()
                if not cname:
                    continue
                cat = session.exec(
                    select(Category).where(Category.family_id == family.id, Category.name == cname)
                ).first()
                if not cat:
                    cat = Category(family_id=family.id, name=cname)
                    session.add(cat)
                    session.commit()
                    session.refresh(cat)
                category_map[cname] = cat
        except Exception as e:
            logger.warning("Categories extraction skipped: %s", e)

        # 4. 迁移历史支出 Expenses -> Transactions (负值)
        migrated_expenses = 0
        try:
            src_cur.execute("SELECT * FROM expense")
            expenses = src_cur.fetchall()
            for exp in expenses:
                paid_by = exp["paid_by"] if "paid_by" in exp.keys() else None
                acc = account_map.get(paid_by, default_account)

                raw_amt = Decimal(str(exp["amount"]))
                amount = -abs(raw_amt)  # 支出统一记录为负

                # 解析日期
                raw_date = exp["date"]
                transacted_at = datetime.strptime(raw_date, "%Y-%m-%d").date()

                cat_obj = category_map.get(exp["category"]) if "category" in exp.keys() else None

                t = Transaction(
                    account_id=acc.id,
                    external_id=f"legacy_exp_{exp['id']}",
                    transacted_at=transacted_at,
                    amount=amount,
                    currency=family.currency,
                    name=exp["description"] or "历史支出",
                    merchant_name=exp["description"],
                    category_id=cat_obj.id if cat_obj else None,
                    transaction_type="expense",
                    notes=f"从原系统迁移 (ID: {exp['id']})",
                )
                session.add(t)
                migrated_expenses += 1
            session.commit()
            logger.info("Successfully migrated %d expenses.", migrated_expenses)
        except Exception as e:
            logger.warning("Expense migration: %s", e)

        # 5. 迁移历史收入 Incomes -> Transactions (正值)
        migrated_incomes = 0
        try:
            src_cur.execute("SELECT * FROM income")
            incomes = src_cur.fetchall()
            for inc in incomes:
                acc = default_account
                raw_amt = Decimal(str(inc["amount"]))
                amount = abs(raw_amt)  # 收入统一记录为正

                raw_date = inc["date"]
                transacted_at = datetime.strptime(raw_date, "%Y-%m-%d").date()

                t = Transaction(
                    account_id=acc.id,
                    external_id=f"legacy_inc_{inc['id']}",
                    transacted_at=transacted_at,
                    amount=amount,
                    currency=family.currency,
                    name=inc["description"] or "历史收入",
                    transaction_type="income",
                    notes=f"从原系统迁移 (ID: {inc['id']})",
                )
                session.add(t)
                migrated_incomes += 1
            session.commit()
            logger.info("Successfully migrated %d incomes.", migrated_incomes)
        except Exception as e:
            logger.warning("Income migration skipped: %s", e)

    src_conn.close()
    logger.info("Migration complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite database to famLedger.")
    parser.add_argument("--source-db", type=Path, required=True, help="Path to source mosaic.db")
    parser.add_argument("--target-db", type=str, required=True, help="Target DB URL (PostgreSQL or SQLite)")
    args = parser.parse_args()

    migrate(args.source_db, args.target_db)
