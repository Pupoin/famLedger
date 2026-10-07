"""Fixed account and master-card settlement amounts. Never revalue on reads."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session as SASession
from sqlmodel import select

from models import Account, PendingFxTransaction, Transaction, VALID_CURRENCIES

MONEY = Decimal("0.0001")
RATE = Decimal("0.000000000001")


class PendingExchangeRate(Exception):
    pass


def money(value, positive=False):
    value = Decimal(str(value))
    if not value.is_finite() or abs(value) >= Decimal("1000000000000000") or (positive and value <= 0):
        raise HTTPException(422, "金额必须是有效的正数且不超过账本精度")
    rounded = value.quantize(MONEY, rounding=ROUND_HALF_UP)
    if positive and rounded <= 0:
        raise HTTPException(422, "金额小于最小记账单位")
    return rounded


def currency(code):
    code = str(code or "").strip().upper()
    if code not in VALID_CURRENCIES:
        raise HTTPException(422, "币种不受支持")
    return code


def fixed_conversion(session, amount, source, target, day, bank_amount=None, bank_currency=None, source_name="bank"):
    source, target = currency(source), currency(target)
    amount = money(amount)
    if bank_amount is not None:
        if currency(bank_currency) != target:
            raise HTTPException(422, "结算币种必须与账户币种一致")
        result = money(bank_amount, positive=amount > 0)
        rate = (result / amount).quantize(RATE, rounding=ROUND_HALF_UP) if amount else Decimal(1)
        if not rate.is_finite() or rate <= 0 or rate >= Decimal("10000000000000000"):
            raise HTTPException(422, "结算汇率超出可记录精度")
        return result, rate, day, source_name
    if bank_currency is not None:
        raise HTTPException(422, "指定结算币种时必须提供实际结算金额")
    if source == target or not amount:
        return amount, Decimal(1), day, "same_currency"
    from services.report_currency import exchange_rates
    try:
        rates, effective_day = exchange_rates(session, day)
        if source not in rates or target not in rates:
            raise HTTPException(502, "指定日期缺少该币种汇率")
    except HTTPException as error:
        if error.status_code in {422, 502}:
            raise PendingExchangeRate(str(error.detail)) from error
        raise
    rate = (rates[target] / rates[source]).quantize(RATE, rounding=ROUND_HALF_UP)
    return money(amount * rate, positive=amount > 0), rate, effective_day, "frankfurter"


def prepare_booking(session, account, amount, original_currency, day, settlement_amount=None,
                    settlement_currency=None, master_settlement_amount=None,
                    master_settlement_currency=None, source_name="bank", occurred_at=None):
    original = money(amount, positive=True)
    native = currency(original_currency or account.currency)
    booked, rate, rate_day, provider = fixed_conversion(
        session, original, native, account.currency, day, settlement_amount, settlement_currency, source_name)
    fields = dict(amount=booked, currency=account.currency, original_amount=original,
                  original_currency=native, exchange_rate=rate, exchange_rate_date=rate_day,
                  exchange_rate_source=provider)
    from services.card_history import parent_at
    membership = parent_at(session, account, Transaction(account_id=account.id, transacted_at=day,
                           occurred_at=occurred_at, amount=booked, narration=''))
    if membership:
        parent = session.get(Account, membership.master_account_id)
        if parent is None and membership.ended_at is not None:
            parent = Account(id=membership.master_account_id, name='', account_type='credit_card',
                             family_id=account.family_id, currency=membership.settlement_currency)
        if not parent or (membership.ended_at is None and (not parent.is_active or parent.family_id != account.family_id)):
            raise HTTPException(409, "副卡的主卡关系已失效")
        value, master_rate, master_day, master_source = fixed_conversion(
            session, booked, account.currency, parent.currency, day,
            master_settlement_amount, master_settlement_currency, source_name)
        fields.update(master_account_id=parent.id, master_settlement_amount=value,
                      master_settlement_currency=parent.currency, master_exchange_rate=master_rate,
                      master_exchange_rate_date=master_day, master_exchange_rate_source=master_source)
    elif master_settlement_amount is not None or master_settlement_currency is not None:
        raise HTTPException(422, "没有主卡关系，不能填写主卡结算金额")
    return fields


def assign_booking(txn, fields):
    for name, value in fields.items():
        setattr(txn, name, value)


def native_money(txn):
    if txn.original_amount is None or not txn.original_currency:
        raise HTTPException(409, "历史流水缺少已核实的原币信息，请先确认原币与实际结算金额")
    return txn.original_amount, txn.original_currency


def master_fields(txn, session, account, force=False):
    from services.card_history import parent_at
    membership = parent_at(session, account, txn)
    if membership is None:
        for name in ("master_account_id", "master_settlement_amount", "master_settlement_currency",
                     "master_exchange_rate", "master_exchange_rate_date", "master_exchange_rate_source"):
            setattr(txn, name, None)
        return
    parent = session.get(Account, membership.master_account_id)
    if parent is None and membership.ended_at is not None:
        parent = Account(id=membership.master_account_id, name='', account_type='credit_card',
                         family_id=account.family_id, currency=membership.settlement_currency)
    if parent is None:
        parent = next((row for row in session.new if isinstance(row, Account) and row.id == membership.master_account_id), None)
    if not parent or (membership.ended_at is None and (not parent.is_active or parent.family_id != account.family_id)):
        raise HTTPException(409, "副卡主卡关系无效")
    if not force and txn.master_account_id == parent.id and txn.master_settlement_amount is not None:
        return
    if account.currency != parent.currency:
        native_money(txn)
    value, rate, day, provider = fixed_conversion(session, txn.amount, account.currency, parent.currency, txn.transacted_at)
    txn.master_account_id, txn.master_settlement_amount = parent.id, value
    txn.master_settlement_currency, txn.master_exchange_rate = parent.currency, rate
    txn.master_exchange_rate_date, txn.master_exchange_rate_source = day, provider


def money_metadata(txn):
    def value(name):
        result = getattr(txn, name, None)
        return result.isoformat() if isinstance(result, date) else str(result) if isinstance(result, Decimal) else str(result) if name == "master_account_id" and result else result
    names = ("original_amount", "original_currency", "exchange_rate", "exchange_rate_date", "exchange_rate_source",
             "master_account_id", "master_settlement_amount", "master_settlement_currency", "master_exchange_rate",
             "master_exchange_rate_date", "master_exchange_rate_source")
    return {**{name: value(name) for name in names}, "needs_money_review": txn.original_amount is None or not txn.original_currency}


@event.listens_for(SASession, "before_flush")
def complete_ledger_money(session, flush_context, instances):
    """Cover opening/reconciliation/transfers as well as the ingestion service.

    Existing rows receive no guessed provenance. Only new ledger activities and
    deliberate financial edits are prepared; ordinary reads/notes stay fixed.
    """
    with session.no_autoflush:
        from services.card_history import maintain_memberships, history_exists
        maintain_memberships(session)
        changed_accounts = [row for row in session.dirty if isinstance(row, Account)]
        for account in changed_accounts:
            state = inspect(account)
            if state.attrs.currency.history.has_changes():
                has_rows = session.execute(select(Transaction.id).where(Transaction.account_id == account.id)).first()
                has_pending = session.execute(select(PendingFxTransaction.id).where(PendingFxTransaction.account_id == account.id)).first()
                has_children = session.execute(select(Account.id).where(Account.parent_account_id == account.id)).first()
                if has_rows or has_pending or account.parent_account_id or has_children or history_exists(session, account.id):
                    raise HTTPException(400, "有流水、待入账记录或主副卡关系的账户不能直接修改币种，请新建正确币种账户")
            if state.attrs.parent_account_id.history.has_changes():
                for txn in session.execute(select(Transaction).where(Transaction.account_id == account.id)).scalars().all():
                    master_fields(txn, session, account)
        for txn in list(session.new) + list(session.dirty):
            if not isinstance(txn, Transaction) or txn in session.deleted:
                continue
            state = inspect(txn)
            financial_change = any(state.attrs[name].history.has_changes() for name in
                                   ("amount", "currency", "account_id", "original_amount", "original_currency", "transacted_at", "occurred_at"))
            if txn not in session.new and not financial_change:
                continue
            account = session.get(Account, txn.account_id)
            if account is None:
                account = next((a for a in session.new if isinstance(a, Account) and a.id == txn.account_id), None)
            if account is None:
                continue  # The database FK reports an invalid account.
            if txn.currency != account.currency:
                raise HTTPException(400, "流水记账币种必须与账户币种一致")
            if txn in session.new and txn.original_amount is None:
                txn.original_amount, txn.original_currency = txn.amount, txn.currency
                txn.exchange_rate, txn.exchange_rate_date, txn.exchange_rate_source = Decimal(1), txn.transacted_at, "same_currency"
            if txn not in session.new and state.attrs.amount.history.has_changes():
                if txn.original_currency == txn.currency:
                    if not state.attrs.exchange_rate.history.has_changes() and not state.attrs.original_amount.history.has_changes():
                        txn.original_amount = txn.amount
                elif not state.attrs.exchange_rate.history.has_changes() and txn.original_amount is not None:
                    txn.exchange_rate = (txn.amount / txn.original_amount).quantize(RATE, rounding=ROUND_HALF_UP)
                    txn.exchange_rate_source = "manual_confirmation"
            master_changed = any(state.attrs[name].history.has_changes() for name in
                                 ("master_settlement_amount", "master_account_id", "master_exchange_rate"))
            master_fields(txn, session, account, force=txn not in session.new and financial_change and not master_changed)


def money_text(value):
    text = format(money(value), ".4f").rstrip("0")
    whole, fraction = text.split(".")
    return whole + "." + fraction.ljust(2, "0")


def master_contribution(session, child, parent):
    """Sum each fixed child settlement once, with the child's activity direction."""
    activities = session.exec(select(Transaction).where(Transaction.account_id == child.id)).all()
    if not activities:
        if child.currency != parent.currency and child.balance:
            raise HTTPException(409, "外币副卡期初余额缺少已核实的主卡结算，请先核对")
        return child.balance or Decimal(0)
    total = Decimal(0)
    from services.transaction_direction import transaction_direction
    for activity in activities:
        if activity.transaction_type not in {"expense", "income", "refund", "transfer", "adjustment"}:
            continue
        if activity.master_account_id == parent.id and activity.master_settlement_currency == parent.currency and activity.master_settlement_amount is not None:
            value = activity.master_settlement_amount
        elif child.currency == parent.currency and activity.master_settlement_amount is None:
            value = activity.amount
        else:
            raise HTTPException(409, "外币副卡历史流水缺少固定主卡结算，请先核对")
        incoming = activity.transaction_type in {"income", "refund"} or (activity.transaction_type == "transfer" and transaction_direction(activity, session, child) == "inflow") or (activity.transaction_type == "adjustment" and (activity.extra or {}).get("direction") == "decrease")
        total += -value if incoming else value
    return total
