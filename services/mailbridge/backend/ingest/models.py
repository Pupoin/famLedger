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
    original_currency: str = "CNY"
    account_type: str = "checking"
    payer_name: str | None = None
    payer_account_last4: str | None = None
    payee_name: str | None = None
    payee_account_last4: str | None = None
