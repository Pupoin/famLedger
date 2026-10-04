"""A supplementary card stays linked only while its primary owner can read it."""

from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import select

from models import Account, AccountShare, User


def primary_owner_can_read(session, child, parent):
    """A link consumes existing ownership or sharing; it never grants access."""
    owner = session.get(User, parent.owner_id) if parent.owner_id else None
    if not owner or owner.family_id != child.family_id:
        return False
    if child.owner_id == parent.owner_id:
        return True
    return session.scalars(select(AccountShare).where(
        AccountShare.account_id == child.id,
        AccountShare.user_id == parent.owner_id,
    )).first() is not None


def detach_unshared_cards(session):
    """Repair links using the pending transaction, without granting new access.

    This also covers ownership transfers, family moves, and account deletion.
    Checking the final pending state keeps cancellation and unlinking atomic,
    without unlinking cards during an intermediate flush in a family move.
    """
    deleted = {id(obj) for obj in session.deleted}
    with session.no_autoflush:
        children = {card.id: card for card in session.scalars(
            select(Account).where(Account.parent_account_id.is_not(None))
        ).all()}
        for card in list(session.new) + list(session.dirty):
            if isinstance(card, Account) and card.parent_account_id is not None:
                children[card.id] = card
        if not children:
            return []

        shares = list(session.scalars(select(AccountShare).where(
            AccountShare.account_id.in_(children)
        )).all())
        shares.extend(obj for obj in session.new if isinstance(obj, AccountShare))
        shared_pairs = {(share.account_id, share.user_id) for share in shares if id(share) not in deleted}
        pending_accounts = {card.id: card for card in session.new if isinstance(card, Account)}
        pending_users = {user.id: user for user in session.new if isinstance(user, User)}
        detached = []
        for child in children.values():
            if id(child) in deleted or child.parent_account_id is None:
                continue
            parent = pending_accounts.get(child.parent_account_id) or session.get(Account, child.parent_account_id)
            owner = (pending_users.get(parent.owner_id) or session.get(User, parent.owner_id)) if parent else None
            valid = (parent is not None and id(parent) not in deleted and owner is not None and id(owner) not in deleted
                     and parent.id != child.id and parent.family_id == child.family_id
                     and owner.family_id == child.family_id
                     and (child.owner_id == parent.owner_id or (child.id, parent.owner_id) in shared_pairs))
            if not valid:
                child.parent_account_id = None
                session.add(child)
                detached.append(child.id)
        return detached


def _has_card_changes(session):
    return any(isinstance(obj, (Account, AccountShare, User))
               for obj in list(session.new) + list(session.dirty) + list(session.deleted))


@event.listens_for(OrmSession, "after_flush")
def _remember_card_changes(session, flush_context):
    if _has_card_changes(session):
        session.info["card_sharing_check_pending"] = True


@event.listens_for(OrmSession, "before_commit")
def _maintain_card_sharing(session):
    if session.info.get("card_sharing_check_pending") or _has_card_changes(session):
        detach_unshared_cards(session)


@event.listens_for(OrmSession, "after_commit")
@event.listens_for(OrmSession, "after_rollback")
def _clear_card_check(session):
    session.info.pop("card_sharing_check_pending", None)
