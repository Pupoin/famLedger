"""Shared dashboard authorization and report participation scope."""
from sqlmodel import select
from models import Account, User


def dashboard_scope(session, user_or_ctx, user_filter):
    # 1. Resolve current user name & family members
    current_user_name = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user_name = user_or_ctx
    elif isinstance(user_or_ctx, dict):
        current_user_name = user_or_ctx.get("username")

    user_db = None
    if current_user_name:
        user_db = session.exec(select(User).where(User.username == current_user_name)).first()

    if not user_db:
        # 服务端 Key 情况下找第一个拥有 family 的用户或首个有效用户
        user_db = session.exec(select(User).where(User.family_id != None)).first()

    current_user = user_db.username if user_db else (current_user_name or "user")
    display_name = user_db.display_name if user_db and user_db.display_name else current_user

    # Fetch family members
    family_id = user_db.family_id if user_db else None

    family_members = []
    if family_id:
        all_m = session.exec(select(User).where(User.family_id == family_id)).all()
        for m in all_m:
            family_members.append({
                "id": str(m.id),
                "username": m.username,
                "display_name": m.display_name or m.username,
                "is_current": m.username == current_user,
            })

    # 2. Determine allowed and filtered accounts
    from models import AccountShare
    shares = session.exec(select(AccountShare)).all()
    user_shares = {s.account_id: s for s in shares if user_db and s.user_id == user_db.id}

    from services.stats_engine import get_family_active_account_ids

    family_active_ids = get_family_active_account_ids(session, family_id)
    all_family_accounts = session.exec(
        select(Account).where(Account.id.in_(family_active_ids)) if family_active_ids else select(Account).where(False)
    ).all()

    # Permissions filter for current user: 严格基于自己拥有或他人授权共享，杜绝越权
    visible_accounts = []
    for a in all_family_accounts:
        is_my_acc = user_db and a.owner_id == user_db.id
        sh = user_shares.get(a.id)
        if (is_my_acc or sh or (user_db and user_db.role == "admin")) and not a.exclude_from_reports and (not sh or sh.include_in_finances):
            visible_accounts.append(a)

    # If user_filter is given (e.g. 'alice', 'qq', or a user uuid) and not '全部'/'ALL'
    target_user_obj = None
    if user_filter and user_filter not in ("全部", "ALL", "all", ""):
        for m in (all_m if family_id else []):
            if m.username == user_filter or m.display_name == user_filter or str(m.id) == user_filter:
                target_user_obj = m
                break

    if target_user_obj:
        active_accounts = [a for a in visible_accounts if a.owner_id == target_user_obj.id]
    else:
        active_accounts = visible_accounts

    return user_db, display_name, family_members, active_accounts, all_family_accounts, target_user_obj
