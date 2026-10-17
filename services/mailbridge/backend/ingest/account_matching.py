"""Resolve bank-qualified tails without treating a person's name as ownership."""
import re
import unicodedata


BANKS = ("招商银行", "中国工商银行", "中国建设银行", "中国农业银行", "中国银行",
         "交通银行", "中国邮政储蓄银行", "中信银行", "中国光大银行", "中国民生银行",
         "兴业银行", "平安银行", "上海浦东发展银行", "华夏银行", "广发银行")


def normalized_bank(value):
    text = unicodedata.normalize('NFKC', str(value or '')).strip()
    if '招商银行' in text or '招行' in text or text.casefold() in {'cmb', '招商'}:
        return '招商银行'
    for bank in BANKS:
        if bank in text:
            return bank
    return None


def message_bank(message):
    """The known bank sender wins; a conflicting title prevents inference."""
    senders = set()
    for key in ('from', 'sender'):
        address = ((message.get(key) or {}).get('emailAddress') or {}).get('address', '')
        if str(address).strip().casefold().endswith('@message.cmbchina.com'):
            senders.add('招商银行')
    title_bank = normalized_bank(message.get('subject') or message.get('title'))
    if title_bank:
        senders.add(title_bank)
    return next(iter(senders)) if len(senders) == 1 else None


def account_candidates(accounts, bank, tail, *, account_type=None, include_unavailable=False):
    """Return the strongest matches, retaining ambiguity instead of guessing."""
    if not bank or not re.fullmatch(r'\d{4}', str(tail or '')):
        return []
    matches = [[], [], [], []]
    exact = f"{bank}{'借记卡' if account_type == 'checking' else '信用卡'}:{tail}" if account_type else None
    for account in accounts:
        if not include_unavailable and (account.get('is_active') is False or account.get('relationship_only')):
            continue
        if account_type and account.get('account_type') not in (
            {'checking', 'savings', 'cash', 'debit_card', 'debit', '借记卡', '储蓄卡', '现金'}
            if account_type == 'checking' else {'credit_card', 'credit', '信用卡'}
        ):
            continue
        identifier = unicodedata.normalize('NFKC', str(account.get('external_identifier') or '')).strip()
        text = identifier or str(account.get('name') or '')
        tails = [part[-4:] for part in re.findall(r'\d+', text) if len(part) >= 4]
        if tails != [tail]:
            continue
        identifier_bank = normalized_bank(identifier)
        stored_bank = identifier_bank or normalized_bank(account.get('institution_name')) or normalized_bank(account.get('name'))
        # An explicit identifier with a different/unknown bank is authoritative.
        if identifier and not identifier.isdigit() and identifier_bank is None:
            continue
        if stored_bank == bank:
            priority = 0 if identifier and identifier == exact else 1 if identifier_bank else 2 if identifier else 3
            matches[priority].append(account)
    for candidates in matches:
        if candidates:
            return candidates
    return []


def matching_account(accounts, bank, tail, *, account_type=None):
    """Require one bank+tail match, respecting an explicit external identifier."""
    candidates = account_candidates(accounts, bank, tail, account_type=account_type)
    return candidates[0] if len(candidates) == 1 else None
