"""Every refund entry point uses native quotas and fixed booked offsets."""
import re
from difflib import SequenceMatcher
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import select, func

from models import Account, RefundAllocation, Transaction, User, UserPreference
from services.booking_money import PendingExchangeRate, fixed_conversion, money, native_money, money_text
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


def remaining_native(session, txn, refund=False, exclude_pair=None, allocations=None):
    total, native = native_money(txn)
    key = RefundAllocation.refund_transaction_id if refund else RefundAllocation.original_transaction_id
    allocations = allocations if allocations is not None else session.exec(select(RefundAllocation).where(key == txn.id)).all()
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


def refund_category_editable(session, refund, allocations=None):
    if refund.transaction_type != "refund":
        return True
    if allocations is None:
        allocations = session.exec(select(RefundAllocation).where(
            RefundAllocation.refund_transaction_id == refund.id)).all()
    if not allocations:
        return True
    # Unverified historical allocations must be reviewed before reclassification.
    if refund.original_amount is None or not refund.original_currency:
        return False
    return remaining_native(session, refund, refund=True, allocations=allocations) > 0


def guard_refund_category_edit(session, refund):
    if not refund_category_editable(session, refund):
        raise HTTPException(400, "已全部关联的退款分类随原消费，请修改原消费分类或先解除关联")


def refund_category_details(session, refund, allowed_ids, allocations=None, read=None):
    """Linked categories are live original classifications; only the remainder is editable."""
    from models import Category, TransactionSplit
    from services.stats_engine import classify_transaction, transaction_category_portions
    allocations = allocations if allocations is not None else session.exec(select(RefundAllocation).where(
        RefundAllocation.refund_transaction_id == refund.id)).all()
    account = read.account(refund.account_id) if read else session.get(Account, refund.account_id)
    category_map = (read.family_categories(account.family_id) if read else
        {c.id: c for c in session.exec(select(Category).where(Category.family_id == account.family_id)).all()}) if account else {}
    categories = {}
    for allocation in allocations:
        original = read.transaction(allocation.original_transaction_id) if read else session.get(Transaction, allocation.original_transaction_id)
        if not original or original.account_id not in allowed_ids:
            continue
        original_account = read.account(original.account_id) if read else session.get(Account, original.account_id)
        if not original_account or not account or original_account.family_id != account.family_id:
            continue
        splits = (read.transaction_splits(original) if read else session.exec(select(TransactionSplit).where(
            TransactionSplit.transaction_id == original.id)).all()) if original.is_split else []
        for category, weight in transaction_category_portions(original, splits, Decimal(1), category_map):
            if weight > 0:
                categories[category['id']] = category
    return {"category_editable": refund_category_editable(session, refund, allocations),
            "linked_categories": list(categories.values()),
            "unallocated_category": classify_transaction(refund, category_map)}


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
    name = re.sub(r"退款|退货|撤销|refunds?|returns?", "", str(name or "").casefold())
    return re.sub(r"[\W_]+", "", name)


AUTO_REFUND_THRESHOLD = 0.9
AUTO_REFUND_MARGIN = 0.03


def refund_actor(session, principal):
    if isinstance(principal, str):
        return principal if principal.startswith("service:") else session.exec(
            select(User).where(User.username == principal)).first()
    return principal


def auto_refund_enabled(session, principal, account=None):
    actor = refund_actor(session, principal)
    # Service imports follow the account owner's preference, never a global toggle.
    if isinstance(actor, str):
        actor = session.get(User, account.owner_id) if account and account.owner_id else None
    if not actor:
        return False
    pref = session.exec(select(UserPreference).where(UserPreference.username == actor.username)).first()
    return pref.auto_refund_enabled if pref else True


def refund_match_score(refund, original, remaining, *, allow_partial=False, allow_cross_currency=False, allow_historical=False):
    """Opposite directions and verified native quotas are hard gates.

    Amount 30%, narration 35%, merchant name 20%, recency 10%, same account 5%.
    Explicit direction metadata cannot contradict the transaction's type.
    Only manual recommendations may relax the full-quota/same-currency gates;
    automation retains its existing strict eligibility checks.
    """
    def valid_direction(txn, kind, direction):
        explicit = (txn.extra or {}).get("direction")
        aliases = {"inflow": (None, "in", "inflow"), "outflow": (None, "out", "outflow")}
        return txn.transaction_type == kind and explicit in aliases[direction]

    if not valid_direction(refund, "refund", "inflow") or not valid_direction(original, "expense", "outflow"):
        return 0.0, {"opposite_directions": False}
    same_currency = refund.original_currency == original.original_currency
    if (refund.original_amount is None or original.original_amount is None
            or not refund.original_currency or not original.original_currency
            or (not same_currency and not allow_cross_currency)
            or refund.original_amount <= 0 or remaining <= 0
            or (not allow_partial and remaining < refund.original_amount)):
        return 0.0, {"opposite_directions": True, "eligible_amount": False}
    days = (refund.transacted_at - original.transacted_at).days
    if days < 0 or (days > 90 and not allow_historical):
        return 0.0, {"opposite_directions": True, "eligible_date": False}

    def similarity(a, b):
        a, b = merchant_name(a), merchant_name(b)
        return SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0

    def name(txn):
        extra = txn.extra or {}
        return extra.get("merchant_name") or extra.get("merchant") or txn.narration

    amount_similarity = (min(refund.original_amount, remaining) / max(refund.original_amount, remaining)
                         if same_currency else Decimal(0))
    parts = {"amount": float(amount_similarity),
             "narration": similarity(refund.narration, original.narration),
             "name": similarity(name(refund), name(original)),
             "time": max(0, 1 - days / 90), "same_account": float(refund.account_id == original.account_id),
             "opposite_directions": True, "days_apart": days}
    score = sum(parts[key] * weight for key, weight in
                (("amount", .30), ("narration", .35), ("name", .20), ("time", .10), ("same_account", .05)))
    return round(score, 12), parts


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
    if (not auto_refund_enabled(session, principal, account) or refund.excluded_from_stats
            or (refund.extra or {}).get("auto_refund_blocked")):
        return None
    if session.exec(select(RefundAllocation.id).where(RefundAllocation.refund_transaction_id == refund.id)).first():
        return None  # Never overwrite manual or already allocated refunds.
    if refund.refund_of_transaction_id:
        return None  # Legacy explicit links require verification, not a guessed replacement.
    actor = refund_actor(session, principal)
    ids = get_user_writable_account_ids(session, actor, account.family_id)
    if not ids or not refund.original_currency or refund.original_amount is None:
        return None
    candidates = session.exec(select(Transaction).where(
        Transaction.account_id.in_(ids), Transaction.transaction_type == "expense",
        Transaction.excluded_from_stats == False,
        Transaction.original_currency == refund.original_currency,
        Transaction.transacted_at <= refund.transacted_at,
        Transaction.transacted_at >= refund.transacted_at - timedelta(days=90))).all()
    used = dict(session.exec(select(RefundAllocation.original_transaction_id,
        func.sum(RefundAllocation.allocated_amount)).where(
            RefundAllocation.original_transaction_id.in_([row.id for row in candidates]))
        .group_by(RefundAllocation.original_transaction_id)).all()) if candidates else {}
    ranked = []
    for row in candidates:
        if row.original_amount is None or not row.original_currency:
            continue
        remaining = max(Decimal(0), row.original_amount - used.get(row.id, Decimal(0)))
        score, parts = refund_match_score(refund, row, remaining)
        if score > 0:
            ranked.append((score, str(row.id), row, parts))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return None
    best = ranked[0]
    ambiguous = len(ranked) > 1 and best[0] - ranked[1][0] < AUTO_REFUND_MARGIN
    matched = best[0] > AUTO_REFUND_THRESHOLD and not ambiguous
    refund.extra = {**(refund.extra or {}), "refund_match": {
        "score": round(best[0], 6), "threshold": AUTO_REFUND_THRESHOLD,
        "components": best[3], "status": "matched" if matched else "ambiguous" if ambiguous else "below_threshold"}}
    session.add(refund)
    if not matched:
        return None
    try:
        return allocate(session, principal, refund, best[2])
    except PendingExchangeRate:
        # A best-effort automation must not reject an otherwise booked refund.
        refund.extra = {**(refund.extra or {}), "refund_match": {
            **refund.extra["refund_match"], "status": "pending_fx"}}
        session.add(refund)
        return None


def match_historical_refunds(session, principal):
    """Explicit, repeatable replay within the caller's writable account scope."""
    from services.stats_engine import get_user_writable_account_ids
    lock_mutation(session)
    actor = refund_actor(session, principal)
    if not actor:
        raise HTTPException(401, "用户未认证")
    from services.principals import resolve_family_id
    family_id = resolve_family_id(session, principal if isinstance(principal, str) else principal.username)
    ids = get_user_writable_account_ids(session, actor, family_id)
    if not ids:
        return {"examined": 0, "matched": 0, "pending": 0}
    linked = select(RefundAllocation.refund_transaction_id)
    rows = session.exec(select(Transaction).where(Transaction.account_id.in_(ids),
        Transaction.transaction_type == "refund", Transaction.excluded_from_stats == False,
        Transaction.id.not_in(linked)).order_by(Transaction.transacted_at, Transaction.id)).all()
    matched = 0
    for refund in rows:
        matched += auto_allocate(session, principal, refund) is not None
    return {"examined": len(rows), "matched": matched, "pending": len(rows) - matched}


def allocation_metadata(row):
    names = ("allocated_amount", "original_currency", "original_book_amount", "original_book_currency",
             "refund_original_amount", "refund_original_currency", "refund_book_amount", "refund_book_currency",
             "fx_difference_amount", "fx_difference_currency")
    return {name: money_text(getattr(row, name)) if isinstance(getattr(row, name), Decimal) else getattr(row, name) for name in names}


def report_offsets(session, refund, allowed_account_ids, report_money):
    """Offset original booked spending; show actual cash/FX independently."""
    read = report_money.read
    raw = read.transaction(refund.id)
    read.prepare([raw])
    links = read.allocations[refund.id]
    portions, used_book, gain, loss = [], Decimal(0), Decimal(0), Decimal(0)
    for row in links:
        original = read.transaction(row.original_transaction_id)
        if not original or original.account_id not in allowed_account_ids:
            continue
        if row.original_book_amount is not None and row.refund_book_amount is not None:
            original_book, refund_book = row.original_book_amount, row.refund_book_amount
        elif original.original_amount and raw.original_amount and original.original_currency == raw.original_currency:
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
    refunds = list(refunds)
    converter.read.load_transactions(row.id for row in refunds)
    converter.read.prepare(converter.read.transactions[row.id] for row in refunds)
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
