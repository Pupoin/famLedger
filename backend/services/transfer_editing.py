"""Keep an explicitly edited transfer and its counterpart in one transaction."""
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import select

from models import Account, RefundAllocation, Transaction, TransactionSplit, Transfer
from services.booking_money import assign_booking, money, prepare_booking
from services.schedules import guard_transaction
from services.transaction_deletion import transfer_pair
from services.transaction_direction import transaction_direction


def normalize_transfer_payload(session, txn, payload):
    """Map the current side's explicit account/amount to the ordinary edit fields."""
    if (payload.transaction_type or txn.transaction_type) != 'transfer':
        return
    direction = payload.transfer_direction or transaction_direction(txn, session, session.get(Account, txn.account_id)) or 'outflow'
    account_field = 'from_account_id' if direction == 'outflow' else 'to_account_id'
    if account_field in payload.model_fields_set:
        own_id = getattr(payload, account_field)
        if own_id is None:
            raise HTTPException(400, "当前流水所属账户不能为空。")
        if payload.account_id is not None and payload.account_id != own_id:
            raise HTTPException(400, "所属账户与转账方向中的账户不一致。")
        payload.account_id = own_id
    amount_field = 'source_amount' if direction == 'outflow' else 'destination_amount'
    own_amount = getattr(payload, amount_field)
    if own_amount is not None:
        if payload.amount is not None and payload.amount != own_amount:
            raise HTTPException(400, "当前流水金额与转账方向中的金额不一致。")
        payload.amount = own_amount


def validate_transfer_edit(session, actor, txn, payload, target_account, authorize, authorize_receive):
    resulting_type = payload.transaction_type or txn.transaction_type
    explicit_accounts = bool({'from_account_id', 'to_account_id'} & payload.model_fields_set)
    if resulting_type != 'transfer':
        if explicit_accounts or payload.source_amount is not None or payload.destination_amount is not None or payload.transfer_direction is not None:
            raise HTTPException(400, "只有转账可以设置转出、转入账户及金额。")
        return None
    account = target_account or session.get(Account, txn.account_id)
    pair, other = transfer_pair(session, txn)
    old_direction = transaction_direction(txn, session, session.get(Account, txn.account_id))
    direction = old_direction or ('inflow' if txn.transaction_type in {'income', 'refund'} else 'outflow')
    if payload.transfer_direction:
        if pair and payload.transfer_direction != direction:
            raise HTTPException(400, "已配对转账不能直接反转方向，请先解除配对。")
        direction = payload.transfer_direction
    outgoing = direction == 'outflow'
    peer_field = 'to_account_id' if outgoing else 'from_account_id'
    explicit_target = peer_field in payload.model_fields_set
    requested_peer = getattr(payload, peer_field)
    peer_amount = payload.destination_amount if outgoing else payload.source_amount
    if pair and explicit_target and requested_peer is None:
        raise HTTPException(400, "请先解除转账配对，再改成外部账户转账。")
    peer_id = requested_peer if explicit_target else other.account_id if pair else None
    peer_account = session.get(Account, peer_id) if peer_id else None
    if peer_id:
        if not peer_account or not peer_account.is_active:
            raise HTTPException(400, "指定的转账对端账户不存在或已停用。")
        if peer_account.id == account.id:
            raise HTTPException(400, "转入与转出不能为同一账户")
        if peer_account.family_id != account.family_id:
            raise HTTPException(403, "转账两侧账户必须属于同一家庭。")
    if peer_amount is not None and not peer_account:
        raise HTTPException(400, "请先选择转账对端账户。")
    different_currency = peer_account and peer_account.currency != account.currency
    changing_target = bool(peer_account and (not other or peer_account.id != other.account_id))
    own_currency_changed = account.currency != txn.currency
    if (changing_target or own_currency_changed) and different_currency and peer_amount is None:
        raise HTTPException(422, "跨币种转账请核实两侧实际金额。")
    if peer_account and not different_currency and peer_amount is not None:
        if peer_amount != (payload.settlement_amount or payload.amount or txn.amount):
            raise HTTPException(422, "同币种转账的到账金额必须等于转出金额。")
    at = payload.occurred_at.replace(tzinfo=None) if payload.occurred_at else None
    changing_peer = bool(pair and (
        changing_target or target_account or (payload.amount is not None and payload.amount != txn.amount)
        or (at is not None and at != txn.occurred_at)
        or (payload.transacted_at is not None and payload.transacted_at != txn.transacted_at)
        or (payload.date is not None and payload.date != txn.transacted_at.isoformat())
        or any(getattr(payload, name, None) is not None for name in (
            'source_amount', 'destination_amount', 'original_amount', 'original_currency', 'settlement_amount', 'master_settlement_amount'))))
    if pair and changing_peer:
        authorize(session, actor, other.account_id, "修改转账对端")
        guard_transaction(other)
        if session.exec(select(RefundAllocation.id).where(
            (RefundAllocation.original_transaction_id == other.id) | (RefundAllocation.refund_transaction_id == other.id)
        )).first() or session.exec(select(TransactionSplit.id).where(TransactionSplit.transaction_id == other.id)).first():
            raise HTTPException(400, "请先解除转账对端的退款关联或分类拆分。")
    if peer_account and (not pair or changing_target or changing_peer):
        # Existing readonly postings remain immutable: the old peer above must
        # still be writable. Only the destination of a newly credited leg may
        # use the narrower receive permission; a source always requires write.
        checker = authorize_receive if outgoing else authorize
        checker(session, actor, peer_account.id, "转入资金" if outgoing else "转出资金")
    if peer_account and not pair and session.exec(select(TransactionSplit.id).where(TransactionSplit.transaction_id == txn.id)).first():
        raise HTTPException(400, "请先解除分类拆分，再设置转账对端。")
    return {'pair': pair, 'other': other, 'peer_account': peer_account, 'outgoing': outgoing,
            'changing_peer': changing_peer, 'old_amount': txn.amount, 'peer_amount': peer_amount}


def apply_transfer_edit(session, txn, payload, context):
    if not context:
        return
    pair, other, peer_account = context['pair'], context['other'], context['peer_account']
    if pair and not context['changing_peer']:
        return
    outgoing = context['outgoing']
    account = session.get(Account, txn.account_id)
    peer_amount = context['peer_amount']
    if peer_account and peer_account.currency == account.currency and peer_amount is not None and peer_amount != txn.amount:
        raise HTTPException(422, "同币种转账的到账金额必须等于转出金额。")
    if not pair and not peer_account:
        txn.extra = {**(txn.extra or {}), 'direction': 'outflow' if outgoing else 'inflow'}
        return
    if not pair:
        quantity = peer_amount or txn.amount
        fields = prepare_booking(session, peer_account, quantity, peer_account.currency, txn.transacted_at,
                                 quantity, peer_account.currency, source_name='manual_confirmation', occurred_at=txn.occurred_at)
        other = Transaction(account_id=peer_account.id, transacted_at=txn.transacted_at,
                            occurred_at=txn.occurred_at, narration=txn.narration, transaction_type='transfer',
                            notes=txn.notes, status='cleared', **fields)
        session.add_all([txn, other]); session.flush()
        out, incoming = (txn, other) if outgoing else (other, txn)
        pair = Transfer(family_id=account.family_id, outflow_transaction_id=out.id,
                        inflow_transaction_id=incoming.id, amount=out.amount)
        session.add(pair); session.flush()
        txn.transfer_id = other.transfer_id = pair.id
    elif context['changing_peer']:
        old_account_id, old_amount = other.account_id, other.amount
        other_account = peer_account
        if other_account.currency == account.currency:
            quantity = txn.amount
        elif peer_amount is not None:
            quantity = peer_amount
        else:
            # Retain an existing verified exchange ratio when changing only the
            # amount of a cross-currency pair; never copy unlike currencies.
            quantity = money(old_amount * txn.amount / context['old_amount'])
        if quantity <= 0:
            raise HTTPException(422, "转账到账金额必须大于 0。")
        if other.account_id != other_account.id or quantity != old_amount:
            native = quantity
            code = other_account.currency
            master_amount = master_currency = None
            if other.account_id == other_account.id and other.original_amount is not None and other.original_currency:
                native = money(other.original_amount * quantity / old_amount)
                code = other.original_currency
                if other.master_settlement_amount is not None and txn.transacted_at == other.transacted_at:
                    master_amount = money(other.master_settlement_amount * quantity / old_amount)
                    master_currency = other.master_settlement_currency
            fields = prepare_booking(session, other_account, native, code, txn.transacted_at,
                                     quantity, other_account.currency, master_amount, master_currency,
                                     'manual_confirmation', occurred_at=txn.occurred_at)
            # A moved counterpart must not retain the former card's settlement.
            for name in ('master_account_id', 'master_settlement_amount', 'master_settlement_currency',
                         'master_exchange_rate', 'master_exchange_rate_date', 'master_exchange_rate_source'):
                setattr(other, name, None)
            assign_booking(other, fields)
        other.account_id = other_account.id
        other.transacted_at, other.occurred_at = txn.transacted_at, txn.occurred_at
        if old_account_id == other.account_id and quantity == old_amount:
            from services.booking_money import master_fields
            master_fields(other, session, other_account)
        pair.amount = txn.amount if outgoing else other.amount
    out, incoming = (txn, other) if outgoing else (other, txn)
    out.extra = {**(out.extra or {}), 'direction': 'outflow', 'to_account_id': str(incoming.account_id)}
    incoming.extra = {**(incoming.extra or {}), 'direction': 'inflow', 'from_account_id': str(out.account_id)}
    session.add_all([txn, other, pair])
