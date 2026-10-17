"""Complete explicit imported transfers without posting an observed leg twice."""
import uuid
import re
from datetime import timedelta

from fastapi import HTTPException
from sqlmodel import select

from models import Account, RejectedTransfer, RefundAllocation, Transaction, TransactionSplit, Transfer
from services.booking_money import prepare_booking
from services.schedules import guard_transaction
from services.transaction_deletion import transfer_pair
from services.transaction_direction import transaction_direction


def transfer_context(session, actor, account, data, authorize, authorize_receive, resolve_account=None):
    extra = data.extra or {}
    source, destination = extra.get('from_account_id'), extra.get('to_account_id')
    source_identifier, destination_identifier = extra.get('from_account_identifier'), extra.get('to_account_identifier')
    selector = source_identifier or destination_identifier
    if sum(bool(value) for value in (source, destination, source_identifier, destination_identifier)) > 1:
        raise HTTPException(422, '单笔流水只能指定一个转账对端账户')
    if not source and not destination and not selector:
        authorize(session, actor, account.id, '记账')
        return None
    outgoing = bool(destination or destination_identifier)
    if (source or selector) and data.transaction_type != 'transfer':
        raise HTTPException(400, '指定转出账户的流水必须为转账类型')
    direction = extra.get('direction')
    if direction is not None and direction not in (('out', 'outflow') if outgoing else ('in', 'inflow')):
        raise HTTPException(422, '转账方向与指定的对端账户不一致')
    if selector:
        if (not isinstance(selector, str) or not re.fullmatch(r'[^:\s]{1,80}:\d{4}', selector)
                or not resolve_account):
            raise HTTPException(422, '转账对端标识必须为银行名称:四位尾号')
        # Validate access to the reported account before resolving another one.
        (authorize if outgoing else authorize_receive)(session, actor, account.id, '转账')
        existing = session.exec(select(Transaction).where(
            Transaction.account_id == account.id, Transaction.external_id == data.external_id,
        )).first() if data.external_id else None
        if existing and (existing.transfer_id or existing.transaction_type != 'transfer'
                         or (existing.extra or {}).get('transfer_peer_deleted')
                         or (existing.extra or {}).get('import_source') != 'mailbridge'
                         or extra.get('import_source') != 'mailbridge'
                         or not data.occurred_at or existing.occurred_at != data.occurred_at.replace(tzinfo=None)
                         or existing.amount != data.amount or existing.currency != (data.currency or account.currency)
                         or transaction_direction(existing, session, account) != ('outflow' if outgoing else 'inflow')):
            raise HTTPException(409, '原流水已有配对或已修改，请刷新账户并人工核对，不新建对端账户')
        peer = resolve_account(selector)
        # Store the resolved UUID for later FX retries and generated-leg claims.
        field = 'to_account_id' if outgoing else 'from_account_id'
        data.extra = {key: value for key, value in extra.items()
                      if key not in ('from_account_identifier', 'to_account_identifier')}
        data.extra[field] = str(peer.id)
    else:
        try:
            peer = session.get(Account, uuid.UUID(str(destination or source)))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(422, '转账对端账户ID无效')
    if not peer or not peer.is_active or not account.is_active or peer.id == account.id:
        raise HTTPException(400, '转账对端账户无效或已停用')
    if peer.family_id != account.family_id or peer.currency != account.currency:
        raise HTTPException(400, '转账账户必须同家庭同记账币种')
    debit, credit = (account, peer) if outgoing else (peer, account)
    authorize(session, actor, debit.id, '转出资金')
    authorize_receive(session, actor, credit.id, '转入资金')
    return {'peer': peer, 'outgoing': outgoing, 'mailbridge': extra.get('import_source') == 'mailbridge'}


def _same_day_legs(session, txn, account_id):
    rows = session.exec(select(Transaction).where(
        Transaction.account_id == account_id, Transaction.transaction_type == 'transfer',
        Transaction.amount == txn.amount, Transaction.currency == txn.currency,
        Transaction.transacted_at == txn.transacted_at,
    )).all()
    return [row for row in rows if (row.extra or {}).get('import_source') == 'mailbridge'
            and row.occurred_at and txn.occurred_at]


def claim_generated_leg(session, txn, context):
    """An opposite bank notice may identify a leg inferred from the first mail."""
    if not context or not context['mailbridge'] or not txn.external_id:
        return None
    candidates = []
    for row in _same_day_legs(session, txn, txn.account_id):
        if row.external_id or not (row.extra or {}).get('mailbridge_generated_peer'):
            continue
        if (row.extra or {}).get('transfer_peer_deleted'):
            field = 'to_account_id' if context['outgoing'] else 'from_account_id'
            direction = 'outflow' if context['outgoing'] else 'inflow'
            if (row.extra or {}).get(field) != str(context['peer'].id) or (row.extra or {}).get('direction') != direction:
                continue
            raise HTTPException(409, '转账对端已被手动删除，请人工核对，不会自动恢复')
        pair, other = transfer_pair(session, row)
        if (pair and other.account_id == context['peer'].id
                and (pair.outflow_transaction_id == row.id) == context['outgoing']):
            candidates.append(row)
    if len(candidates) > 1:
        raise HTTPException(409, '多笔转账符合银行通知，请人工核对后重试，未新增流水')
    if not candidates:
        return None
    matched = candidates[0]
    if abs(matched.occurred_at - txn.occurred_at) > timedelta(minutes=2):
        raise HTTPException(409, '存在相同账户和金额的待确认转账，但通知时间差过大，请人工核对，未重复记账')
    if txn.original_currency != matched.original_currency or txn.original_amount != matched.original_amount:
        raise HTTPException(409, '转账原币信息不一致，请人工核对，未重复记账')
    guard_transaction(matched)
    matched.external_id = txn.external_id
    session.add(matched)
    return matched


def attach_transfer_peer(session, txn, context, actor, authorize):
    """Reuse one known opposite posting, otherwise atomically create its leg."""
    peer, outgoing = context['peer'], context['outgoing']
    candidates = []
    uncertain = False
    if context['mailbridge']:
        for row in _same_day_legs(session, txn, peer.id):
            if row.transfer_id or transaction_direction(row, session, peer) != ('inflow' if outgoing else 'outflow'):
                continue
            account_field = 'from_account_id' if outgoing else 'to_account_id'
            explicit_peer = (row.extra or {}).get(account_field)
            if explicit_peer and explicit_peer != str(txn.account_id):
                continue
            if not explicit_peer:
                counterparty = (row.extra or {}).get('counterparty') or {}
                tail = counterparty.get('payer_account_last4' if outgoing else 'payee_account_last4') if isinstance(counterparty, dict) else None
                if tail and tail != (txn.extra or {}).get('account_last4'):
                    continue
                bank = (row.extra or {}).get('counterparty_bank_name')
                same_bank = bank == (txn.extra or {}).get('bank_name') if bank else (
                    '本行' in (row.narration or '') and '他行' not in (row.narration or ''))
                if not tail or not same_bank:
                    uncertain |= abs(row.occurred_at - txn.occurred_at) <= timedelta(minutes=2)
                    continue
            if abs(row.occurred_at - txn.occurred_at) > timedelta(minutes=2):
                uncertain = True
                continue
            if (row.extra or {}).get('transfer_peer_deleted'):
                raise HTTPException(409, '转账对端已被手动删除，请人工核对，不会自动恢复')
            candidates.append(row)
    if uncertain or len(candidates) > 1:
        raise HTTPException(409, '多笔对端转账符合银行通知，请人工核对后重试，未新增流水')
    other = candidates[0] if candidates else None
    if other:
        authorize(session, actor, other.account_id, '配对已有转账流水')
        guard_transaction(other)
        if session.exec(select(TransactionSplit.id).where(TransactionSplit.transaction_id == other.id)).first() or session.exec(
            select(RefundAllocation.id).where((RefundAllocation.refund_transaction_id == other.id)
                                             | (RefundAllocation.original_transaction_id == other.id))).first():
            raise HTTPException(409, '对端流水已有拆分或退款关联，请先人工核对')
        out_id, in_id = (txn.id, other.id) if outgoing else (other.id, txn.id)
        if session.exec(select(RejectedTransfer.id).where(
            RejectedTransfer.outflow_transaction_id == out_id, RejectedTransfer.inflow_transaction_id == in_id,
        )).first():
            raise HTTPException(409, '该转账配对已被手动驳回，不能自动恢复')
    else:
        booking = prepare_booking(session, peer, txn.amount, peer.currency, txn.transacted_at,
                                  txn.amount, peer.currency, source_name='bank', occurred_at=txn.occurred_at)
        extra = {'transaction_type_source': 'manual'}
        if context['mailbridge']:
            extra = {'import_source': 'mailbridge', 'mailbridge_generated_peer': True,
                     'derived_from_external_id': txn.external_id}
        primary_account = session.get(Account, txn.account_id)
        narration = txn.narration
        if context['mailbridge']:
            narration = f'收到{primary_account.name}转入' if outgoing else f'转出到{primary_account.name}'
        other = Transaction(account_id=peer.id, **booking, narration=narration,
                            transaction_type='transfer', category_id=txn.category_id, category_source=txn.category_source,
                            transacted_at=txn.transacted_at, occurred_at=txn.occurred_at,
                            notes=txn.notes, status='posted', extra=extra)
        session.add(other)
    session.flush()
    out, incoming = (txn, other) if outgoing else (other, txn)
    pair = Transfer(family_id=peer.family_id, outflow_transaction_id=out.id,
                    inflow_transaction_id=incoming.id, amount=out.amount, status='confirmed')
    session.add(pair); session.flush()
    out.transfer_id = incoming.transfer_id = pair.id
    out.extra = {**(out.extra or {}), 'direction': 'outflow', 'to_account_id': str(incoming.account_id)}
    incoming.extra = {**(incoming.extra or {}), 'direction': 'inflow', 'from_account_id': str(out.account_id)}
    session.add_all([out, incoming])
    return pair


def complete_duplicate_import(session, actor, existing, data, context, authorize):
    """A deliberate mail replay may complete a previously one-sided transfer."""
    if (not context or not context['mailbridge'] or existing.transfer_id or not data.occurred_at
            or (existing.extra or {}).get('transfer_peer_deleted')
            or existing.transaction_type != 'transfer' or (existing.extra or {}).get('import_source') != 'mailbridge'
            or existing.occurred_at != data.occurred_at.replace(tzinfo=None)
            or existing.currency != (data.currency or existing.currency)
            or existing.amount != data.amount
            or transaction_direction(existing, session, session.get(Account, existing.account_id))
               != ('outflow' if context['outgoing'] else 'inflow')):
        return
    # Existing labels, amounts and user edits are never overwritten on replay.
    authorize(session, actor, existing.account_id, '补全已有转账配对')
    guard_transaction(existing)
    attach_transfer_peer(session, existing, context, actor, authorize)


def transfer_confirmation(session, txn, context):
    """Confirm the actual pair, including a duplicate's existing counterpart."""
    result = {'transfer_id': str(txn.transfer_id) if txn.transfer_id else None,
              'transfer_context_accepted': False}
    if context and txn.transfer_id:
        pair = session.get(Transfer, txn.transfer_id)
        if pair and pair.family_id == context['peer'].family_id:
            own_id = pair.outflow_transaction_id if context['outgoing'] else pair.inflow_transaction_id
            other_id = pair.inflow_transaction_id if context['outgoing'] else pair.outflow_transaction_id
            other = session.get(Transaction, other_id)
            result['transfer_context_accepted'] = bool(own_id == txn.id and other and other.account_id == context['peer'].id)
    return result
