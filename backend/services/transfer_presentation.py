"""Identify a visible transfer account without pairing or changing its ledger."""
import re
import unicodedata
import uuid

from services.balance_sheet import visible_balance_accounts
from services.transaction_direction import transaction_direction


def _bank(value):
    text = unicodedata.normalize('NFKC', str(value or '')).strip().casefold()
    text = re.sub(r'信用卡|借记卡|储蓄卡|credit[_ ]card|debit[_ ]card', '', text)
    text = re.sub(r'[\s:\d_-]+$', '', text)
    if '招商银行' in text or '招行' in text or text in ('cmb', '招商'):
        return '招商银行'
    return text.removeprefix('中国') if text != '中国银行' else text


def _account_key(account):
    identifier = unicodedata.normalize('NFKC', account.external_identifier or '').strip()
    text = identifier or account.name
    numbers = list(re.finditer(r'\d{4,}', text))
    if len(numbers) != 1:
        return None
    tail = numbers[0].group()[-4:]
    if identifier and not identifier.isdigit():
        bank = _bank(identifier[:numbers[0].start()])
        rank = 0
    else:
        bank = _bank(account.institution_name or text[:numbers[0].start()])
        rank = 1 if identifier else 2
    return (account.family_id, bank, tail), rank


def unpaired_counterparts(session, actor, transactions, accounts):
    """Resolve only explicit pointers or bank-qualified mail data within access."""
    rows = [row for row in transactions if row.transaction_type == 'transfer' and not row.transfer_id
            and ((row.extra or {}).get('counterparty') or (row.extra or {}).get('from_account_id')
                 or (row.extra or {}).get('to_account_id'))]
    if not rows:
        return {}
    visible = {account.id: account for account in visible_balance_accounts(session, actor) if account.is_active}
    index = {}
    for account in visible.values():
        identity = _account_key(account)
        if identity:
            key, rank = identity
            index.setdefault(key, {}).setdefault(rank, []).append(account)
    matched = {}
    for row in rows:
        primary = accounts.get(row.account_id)
        if not primary:
            continue
        extra = row.extra or {}
        outgoing = transaction_direction(row, account=primary) == 'outflow'
        explicit = extra.get('to_account_id' if outgoing else 'from_account_id')
        if explicit:
            try:
                peer = visible.get(uuid.UUID(str(explicit)))
            except (ValueError, TypeError, AttributeError):
                peer = None
        else:
            party = extra.get('counterparty')
            if extra.get('import_source') != 'mailbridge' or not isinstance(party, dict):
                continue
            bank = _bank(extra.get('counterparty_bank_name'))
            tail = party.get('payee_account_last4' if outgoing else 'payer_account_last4')
            if not bank or not re.fullmatch(r'\d{4}', str(tail or '')):
                continue
            tiers = index.get((primary.family_id, bank, tail), {})
            candidates = tiers[min(tiers)] if tiers else []
            peer = candidates[0] if len(candidates) == 1 else None
        if peer and peer.id != primary.id and peer.family_id == primary.family_id:
            matched[row.id] = peer
    return matched


def counterpart_identity(account, user, owner_name):
    return {'account_id': str(account.id), 'account_name': account.name,
            'owner_id': str(account.owner_id) if account.owner_id else None,
            'owner_name': owner_name,
            'is_owner': bool(user and account.owner_id == user.id)}
