"""Every refund entry point uses native quotas and fixed booked offsets."""
import re
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import select

from models import Account, RefundAllocation, Transaction, User
from services.booking_money import fixed_conversion, money, native_money, money_text
from services.transaction_lock import lock_mutation


def authorize(session, principal, txn):
    from services.stats_engine import get_user_writable_account_ids
    account = session.get(Account, txn.account_id)
    if not account or not account.is_active:
        raise HTTPException(409, "交易所属账户已失效")
    actor = principal if isinstance(principal, str) and principal.startswith("service:") else (
        session.exec(select(User).where(User.username == principal)).first() if isinstance(principal, str) else principal)
    if not actor or (not isinstance(actor, str) and not actor.is_active):
        raise HTTPException(403, "操作身份已失效")
    if account.id not in get_user_writable_account_ids(session, actor, account.family_id):
        raise HTTPException(403, "无权关联该账户的退款或消费")
    return account


def remaining_native(session, txn, refund=False, exclude_pair=None):
    total, native = native_money(txn)
    key = RefundAllocation.refund_transaction_id if refund else RefundAllocation.original_transaction_id
    allocations = session.exec(select(RefundAllocation).where(key == txn.id)).all()
    used = Decimal(0)
    for row in allocations:
        if row.id == exclude_pair:
            continue
        if refund:
            if row.refund_original_amount is not None:
                used += row.refund_original_amount
            elif row.original_currency in (None, native):
                used += row.allocated_amount
            else:
                raise HTTPException(409, "历史退款分配缺少明确的原币额度，请先核对")
        else:
            used += row.allocated_amount
    return max(Decimal(0), total - used)


def allocate(session, principal, refund, original, quantity=None, original_currency=None, refund_quantity=None):
    lock_mutation(session)
    if refund.transaction_type != "refund" or original.transaction_type != "expense" or original.id == refund.id:
        raise HTTPException(400, "退款只能关联原消费支出")
    refund_acc, original_acc = authorize(session, principal, refund), authorize(session, principal, original)
    if refund_acc.family_id != original_acc.family_id:
        raise HTTPException(403, "退款与原消费必须属于同一家庭")
    native_total, native_currency = native_money(original)
    refund_total, refund_currency = native_money(refund)
    if original_currency is not None and original_currency != native_currency:
        raise HTTPException(422, "冲抵币种必须是原消费原币")
    if native_currency != refund_currency and (original_currency is None or quantity is None or refund_quantity is None):
        raise HTTPException(400, "不同原币的退款需明确确认原消费冲抵金额、币种及所用退款原币金额")
    pair = session.exec(select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund.id,
                                                    RefundAllocation.original_transaction_id == original.id)).first()
    remaining = remaining_native(session, original, exclude_pair=pair.id if pair else None)
    refund_remaining = remaining_native(session, refund, refund=True, exclude_pair=pair.id if pair else None)
    quantity = money(quantity if quantity is not None else min(remaining, refund_remaining), positive=True)
    refund_quantity = money(refund_quantity if refund_quantity is not None else quantity, positive=True)
    if native_currency == refund_currency and quantity != refund_quantity:
        raise HTTPException(400, "同原币退款的冲抵数量必须与所用退款原币数量一致")
    if quantity > remaining or refund_quantity > refund_remaining:
        raise HTTPException(400, "分配不能超过退款总额或原消费剩余可退额度")
    originals = session.exec(select(RefundAllocation).where(RefundAllocation.original_transaction_id == original.id)).all()
    refunds = session.exec(select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund.id)).all()
    previous_original = sum((a.original_book_amount if a.original_book_amount is not None else
                             money(original.amount * a.allocated_amount / native_total)
                             for a in originals if not pair or a.id != pair.id), Decimal(0))
    previous_refund = sum((a.refund_book_amount if a.refund_book_amount is not None else
                          money(refund.amount * a.allocated_amount / refund_total)
                          for a in refunds if not pair or a.id != pair.id), Decimal(0))
    original_book = money(original.amount - previous_original) if quantity == remaining else min(money(original.amount * quantity / native_total), max(Decimal(0), money(original.amount - previous_original)))
    refund_book = money(refund.amount - previous_refund) if refund_quantity == refund_remaining else min(money(refund.amount * refund_quantity / refund_total), max(Decimal(0), money(refund.amount - previous_refund)))
    converted_refund, _, _, _ = fixed_conversion(session, refund_book, refund.currency, original.currency, refund.transacted_at)
    row = pair or RefundAllocation(refund_transaction_id=refund.id, original_transaction_id=original.id, allocated_amount=quantity)
    row.allocated_amount, row.original_currency = quantity, native_currency
    row.original_book_amount, row.original_book_currency = original_book, original.currency
    row.refund_original_amount, row.refund_original_currency = refund_quantity, refund_currency
    row.refund_book_amount, row.refund_book_currency = refund_book, refund.currency
    row.fx_difference_amount, row.fx_difference_currency = money(converted_refund - original_book), original.currency
    session.add(row)
    session.flush()
    all_links = session.exec(select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund.id)).all()
    refund.refund_of_transaction_id = all_links[0].original_transaction_id if len(all_links) == 1 else None
    if not refund.category_id and original.category_id:
        refund.category_id = original.category_id
    session.add(refund)
    return row


def merchant_name(name):
    name = re.sub(r"退款|退货|撤销|refunds?|returns?", "", (name or "").casefold())
    return re.sub(r"[\W_]+", "", name)


def auto_allocate(session, principal, refund, original_id=None, quantity=None, original_currency=None, refund_quantity=None):
    account = authorize(session, principal, refund)
    if original_id:
        original = session.get(Transaction, original_id)
        if not original:
            raise HTTPException(400, "指定原消费不存在")
        if original.transaction_type != "expense":
            raise HTTPException(400, "指定原交易不是消费")
        authorize(session, principal, original)
        if session.get(Account, original.account_id).family_id != account.family_id:
            raise HTTPException(403, "原消费属于其他家庭")
        if quantity is None and original.original_currency == refund.original_currency:
            remaining = remaining_native(session, original)
            if not remaining:
                return None
        return allocate(session, principal, refund, original, quantity, original_currency, refund_quantity)
    from services.stats_engine import get_user_writable_account_ids
    actor = principal if isinstance(principal, str) and principal.startswith("service:") else session.exec(select(User).where(User.username == principal)).first()
    ids = get_user_writable_account_ids(session, actor, account.family_id)
    name = merchant_name(refund.narration)
    if not name:
        return None
    candidates = session.exec(select(Transaction).where(
        Transaction.account_id.in_(ids), Transaction.transaction_type == "expense",
        Transaction.original_currency == refund.original_currency,
        Transaction.transacted_at <= refund.transacted_at,
        Transaction.transacted_at >= refund.transacted_at - timedelta(days=90))).all()
    candidates = [row for row in candidates if row.original_amount is not None
                  and merchant_name(row.narration) == name and remaining_native(session, row) > 0
                  and row.original_amount >= refund.original_amount]
    if len(candidates) != 1:
        return None
    return allocate(session, principal, refund, candidates[0])


def allocation_metadata(row):
    names = ("allocated_amount", "original_currency", "original_book_amount", "original_book_currency",
             "refund_original_amount", "refund_original_currency", "refund_book_amount", "refund_book_currency",
             "fx_difference_amount", "fx_difference_currency")
    return {name: money_text(getattr(row, name)) if isinstance(getattr(row, name), Decimal) else getattr(row, name) for name in names}


def report_offsets(session, refund, allowed_account_ids, report_money):
    """Offset original booked spending; show actual cash/FX independently."""
    raw = session.get(Transaction, refund.id)
    links = session.exec(select(RefundAllocation).where(RefundAllocation.refund_transaction_id == refund.id)).all()
    portions, used_book, gain, loss = [], Decimal(0), Decimal(0), Decimal(0)
    for row in links:
        original = session.get(Transaction, row.original_transaction_id)
        if not original or original.account_id not in allowed_account_ids:
            continue
        if row.original_book_amount is not None:
            original_book, refund_book = row.original_book_amount, row.refund_book_amount
        elif original.original_amount is not None and raw.original_amount is not None and original.original_currency == raw.original_currency:
            original_book = money(original.amount * row.allocated_amount / original.original_amount)
            refund_book = money(raw.amount * row.allocated_amount / raw.original_amount)
        else:
            continue  # Unverified historical links are shown as requiring review.
        offset = report_money.ledger_amount(original, original_book)
        used_book += refund_book
        # Compare both fixed bookings in the report currency at their own
        # transaction dates. Converting only the stored account-currency FX
        # difference loses the report-currency movement between the two dates.
        difference = report_money.ledger_amount(raw, refund_book) - offset
        gain += max(difference, Decimal(0))
        loss += max(-difference, Decimal(0))
        portions.append((original, offset))
    remainder = report_money.ledger_amount(raw, max(Decimal(0), raw.amount - used_book))
    return portions, remainder, gain, loss


def refund_report_summary(session, refunds, allowed_ids, converter):
    gain, loss, actual, offset = (Decimal(0) for _ in range(4))
    for refund in refunds:
        portions, remainder, g, l = report_offsets(session, refund, allowed_ids, converter)
        gain += g
        loss += l
        actual += Decimal(str(refund.amount))
        offset += sum((value for _, value in portions), Decimal(0)) + remainder
    return {"fx_gain": float(money(gain)), "fx_loss": float(money(loss)),
            "actual_refund_amount": float(money(actual)), "spending_refund_amount": float(money(offset))}


def spending_refund(session, refund, allowed_ids, converter):
    portions, remainder, _, _ = report_offsets(session, refund, allowed_ids, converter)
    return sum((value for _, value in portions), Decimal(0)) + remainder
