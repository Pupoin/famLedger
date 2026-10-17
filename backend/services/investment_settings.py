"""Investment performance settings; a declared capital basis never edits cash."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlmodel import select

from models import Account, InvestmentSetting, Transaction, User
from services.account_types import account_type_is
from services.investments import is_valuation, order, set_valuation, valuation_time
from services.investment_rates import instant, opening
from services.transaction_direction import transaction_direction


def authorized_account(session, principal, account_id, manage=False):
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(404, '账户不存在')
    user = None
    if isinstance(principal, str) and principal.startswith('service:'):
        from services.principals import verify_service_account
        verify_service_account(session, principal, account)
    else:
        user = session.exec(select(User).where(User.username == principal)).first() if isinstance(principal, str) else None
        if user is None:
            raise HTTPException(401, '用户未认证')
        from services.balance_sheet import visible_balance_accounts
        if account_id not in {row.id for row in visible_balance_accounts(session, user)}:
            raise HTTPException(403, '无权查看此投资账户')
    if manage:
        from routes.v1_accounts import _verify_account_management_permission
        _verify_account_management_permission(principal if user is None else user, account, '修改投资设置', session)
    if not account_type_is(account.account_type, 'investment'):
        raise HTTPException(400, '只有投资类型账户可以配置投资统计')
    return account


def contributions(session, rows):
    return [row for row in rows if row.amount > 0 and (opening(row)
            or row.transaction_type == 'transfer' and transaction_direction(row, session) == 'inflow')]


def describe(session, account):
    profile = session.get(InvestmentSetting, account.id)
    rows = sorted(session.exec(select(Transaction).where(Transaction.account_id == account.id)).all(), key=order)
    baseline = next((row for row in rows if profile and row.id == profile.baseline_transaction_id and is_valuation(row)), None)
    capital = contributions(session, rows)
    first = capital[0] if capital else None
    capital_at = profile.capital_occurred_at if profile else None
    if capital_at and capital_at.tzinfo is None:
        capital_at = capital_at.replace(tzinfo=timezone.utc)
    return dict(account_id=str(account.id), currency=account.currency, configured=profile is not None,
        mode=profile.mode if profile else None, baseline_transaction_id=str(baseline.id) if baseline else None,
        occurred_at=instant(baseline).isoformat() if baseline else None,
        target_balance=baseline.extra['target_balance'] if baseline else None,
        capital_amount=str(profile.capital_amount) if profile and profile.capital_amount is not None else None,
        capital_occurred_at=capital_at.isoformat() if capital_at else None,
        can_add_initial=not capital, initial_transaction=dict(id=str(first.id), amount=str(first.amount),
            occurred_at=instant(first).isoformat()) if first else None)


def configure(session, account, payload):
    profile = session.get(InvestmentSetting, account.id) or InvestmentSetting(account_id=account.id, mode=payload.mode)
    if payload.mode == 'capital':
        if any(value is not None for value in (payload.target_balance, payload.occurred_at,
                                              payload.initial_amount, payload.initial_occurred_at)):
            raise HTTPException(422, '本金基准不能携带市值或新增入金流水')
        if payload.capital_amount is None or payload.capital_occurred_at is None:
            raise HTTPException(422, '请填写基准本金和基准日期')
        at, _ = valuation_time(payload.capital_occurred_at)
        profile.capital_amount, profile.capital_occurred_at = payload.capital_amount, at
        profile.baseline_transaction_id = None
    elif payload.capital_amount is not None or payload.capital_occurred_at is not None:
        raise HTTPException(422, '本金基准请使用指定日期本金模式')
    if payload.mode == 'baseline' and (payload.target_balance is None or payload.occurred_at is None):
        raise HTTPException(422, '请填写投资起算市值和日期')
    if payload.mode == 'history' and (payload.target_balance is not None or payload.occurred_at is not None):
        raise HTTPException(422, '历史投入模式请使用真实本金和投入日期')
    rows = session.exec(select(Transaction).where(Transaction.account_id == account.id)).all()
    capital = contributions(session, rows)
    if payload.mode == 'baseline' and (payload.initial_amount is not None or payload.initial_occurred_at is not None):
        raise HTTPException(422, '市值起算不能同时补录历史本金')
    if payload.mode == 'history' and (payload.initial_amount is not None or payload.initial_occurred_at is not None):
        if payload.initial_amount is None or not payload.initial_occurred_at:
            raise HTTPException(422, '请填写初始投入本金和日期')
        at, day = valuation_time(payload.initial_occurred_at)
        if capital:
            raise HTTPException(409, '已有期初或入金流水，请编辑原流水，不能重复添加本金')
        initial = Transaction(account_id=account.id, amount=payload.initial_amount, currency=account.currency,
            transaction_type='income', transacted_at=day, occurred_at=at, narration='投资初始投入',
            excluded_from_stats=True, reconciled=True, category_source='manual', status='cleared',
            extra={'source':'account_opening', 'is_initial':True})
        session.add(initial)
        session.flush()
    if payload.mode == 'baseline':
        from routes.v1_accounts import _ensure_opening_balance_transaction
        _ensure_opening_balance_transaction(session, account)
        at, day = valuation_time(payload.occurred_at)
        baseline = session.get(Transaction, profile.baseline_transaction_id) if profile.baseline_transaction_id else None
        # Deleted or moved-away references never authorize edits to another account.
        if baseline and (baseline.account_id != account.id or not is_valuation(baseline)):
            baseline = None
        if baseline and instant(baseline) != at.replace(tzinfo=timezone.utc):
            # Choosing a new performance starting point must preserve the old
            # dated valuation. Moving a financial record is a separate edit.
            baseline = None
        row = set_valuation(session, account, payload.target_balance, at, day, existing=baseline)
        profile.baseline_transaction_id = row.id
    elif payload.mode == 'history':
        if payload.initial_amount is None and not capital:
            raise HTTPException(422, '请先补录真实的初始投入或入金流水')
        profile.baseline_transaction_id = None
    profile.mode, profile.updated_at = payload.mode, datetime.now(timezone.utc)
    session.add(profile)
    # Settings change the report scope even when no ledger amount changes.
    if payload.mode == 'capital':
        # Invalidate report metadata without replaying or updating any ledger
        # entries just because the statistical basis changed.
        session.execute(Account.__table__.update().where(Account.id == account.id)
                        .values(updated_at=profile.updated_at))
    else:
        account.updated_at = datetime.now(timezone.utc)
        session.add(account)
