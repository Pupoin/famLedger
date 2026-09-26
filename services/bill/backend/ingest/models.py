from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class TransactionRecord:
    cost_time: datetime
    cost: Decimal
    account: str
    behaviour: str
    business: str
    remain: str
    source: str
    original_cost: Decimal | None = None
    original_currency: str | None = None
    payer_name: str | None = None
    payer_account_last4: str | None = None
    payee_name: str | None = None
    payee_account_last4: str | None = None


@dataclass
class DailyCreditSummary:
    used_credit_limit: Decimal
    score: Decimal
