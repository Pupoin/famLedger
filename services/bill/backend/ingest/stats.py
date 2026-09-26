from __future__ import annotations

"""核心统计计算模块。

职责：把数据库原始流水标准化为可展示统计，供后端 Ingest 与前端 Dashboard 共用。
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pandas as pd

from backend.ingest.parser import (
    CREDIT_ACCOUNTS,
    DEBIT_ACCOUNTS,
    DEBIT_IN_BEHAVIOURS,
    DEBIT_OUT_BEHAVIOURS,
)


@dataclass
class FinanceStats:
    """系统统一的统计结果对象。"""
    today_spending: Decimal
    yesterday_spending: Decimal
    month_income: Decimal
    month_outcome: Decimal
    month_debit_income: Decimal
    month_debit_outcome: Decimal
    month_credit_income: Decimal
    month_credit_outcome: Decimal
    current_balance: Decimal
    detail_df: pd.DataFrame


def _as_decimal(value: object) -> Decimal:
    """将任意可数值对象安全转换为 `Decimal`。"""
    return Decimal(str(value))


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """标准化到约定字段。"""
    alias_map = {
        "id": "id",
        "remark": "remark",
        "costtime": "costTime",
        "cost_time": "costTime",
        "account": "account",
        "behaviour": "behaviour",
        "business": "business",
        "remain": "remain",
        "source": "source",
        "cost": "cost",
    }
    rename_map: dict[str, str] = {}
    for col in df.columns:
        lowered = str(col).strip().lower()
        if lowered in alias_map:
            rename_map[col] = alias_map[lowered]

    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def build_stats(month_rows: list[dict], current_balance: Decimal, now: datetime) -> FinanceStats:
    """基于指定时间点构建统计。"""
    if not month_rows:
        empty_df = pd.DataFrame(columns=["costTime", "cost", "account", "behaviour", "business", "remain", "source"])
        return FinanceStats(
            Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
            Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
            current_balance, empty_df,
        )

    df = _normalize_columns(pd.DataFrame(month_rows))
    if "costTime" not in df.columns:
        raise KeyError(f"缺少字段 costTime，当前字段: {list(df.columns)}")
    df["costTime"] = pd.to_datetime(df["costTime"])
    df["cost"] = df["cost"].apply(_as_decimal)
    df = df.loc[df["costTime"] <= pd.Timestamp(now)].copy()

    credit_accounts = CREDIT_ACCOUNTS
    out_behaviours = DEBIT_OUT_BEHAVIOURS 
    in_behaviours = DEBIT_IN_BEHAVIOURS
    debit_accounts = DEBIT_ACCOUNTS

    def calc_income(row: pd.Series) -> Decimal:
        behaviour = str(row.get("behaviour", ""))
        account = str(row.get("account", "")).strip()
        cost = _as_decimal(row["cost"])

        if account in credit_accounts:
            return abs(cost) if cost > 0 else Decimal("0")
        if account in debit_accounts:
            if behaviour in in_behaviours: return abs(cost)
            if behaviour in out_behaviours: return Decimal("0")
            return abs(cost) if cost > 0 else Decimal("0")

        if behaviour in in_behaviours: return abs(cost)
        if behaviour not in out_behaviours and cost > 0 and account not in credit_accounts:
            return cost
        return Decimal("0")

    def calc_outcome(row: pd.Series) -> Decimal:
        behaviour = str(row.get("behaviour", ""))
        account = str(row.get("account", "")).strip()
        cost = _as_decimal(row["cost"])
        if account in credit_accounts:
            return -abs(cost) if cost < 0 else Decimal("0")
        if account in debit_accounts:
            if behaviour in out_behaviours: return -abs(cost)
            if behaviour in in_behaviours: return Decimal("0")
            return -abs(cost) if cost < 0 else Decimal("0")
        if behaviour in out_behaviours: return -abs(cost)
        if behaviour not in in_behaviours and cost < 0: return -abs(cost)
        return Decimal("0")

    df["income"] = df.apply(calc_income, axis=1)
    df["outcome"] = df.apply(calc_outcome, axis=1)
    df["date"] = df["costTime"].dt.date

    today = now.date()
    yesterday = (now - pd.Timedelta(days=1)).date()

    today_spending = sum(df.loc[df["date"] == today, "outcome"], Decimal("0"))
    yesterday_spending = sum(df.loc[df["date"] == yesterday, "outcome"], Decimal("0"))
    month_income = sum(df["income"], Decimal("0"))
    month_outcome = sum(df["outcome"], Decimal("0"))

    debit_df = df.loc[df["account"].astype(str).str.strip().isin(debit_accounts)]
    credit_df = df.loc[df["account"].astype(str).str.strip().isin(credit_accounts)]

    month_debit_income = sum(debit_df["income"], Decimal("0"))
    month_debit_outcome = sum(debit_df["outcome"], Decimal("0"))
    month_credit_income = sum(credit_df["income"], Decimal("0"))
    month_credit_outcome = sum(credit_df["outcome"], Decimal("0"))

    return FinanceStats(
        today_spending=today_spending,
        yesterday_spending=yesterday_spending,
        month_income=month_income,
        month_outcome=month_outcome,
        month_debit_income=month_debit_income,
        month_debit_outcome=month_debit_outcome,
        month_credit_income=month_credit_income,
        month_credit_outcome=month_credit_outcome,
        current_balance=current_balance,
        detail_df=df,
    )
