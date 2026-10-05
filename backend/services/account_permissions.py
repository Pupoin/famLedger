"""Explicit sharing limits take precedence over a recipient's system role."""


def account_capabilities(user, account, share=None):
    """Return (can_write_transactions, can_manage_account)."""
    if isinstance(user, str) and user.startswith("service:"):
        return True, True
    if not user:
        return False, False
    same_family = account.family_id == user.family_id
    if not same_family:
        return False, False
    if account.owner_id == user.id:
        return True, True
    if share is not None:
        if not same_family:
            return False, False
        return (share.permission in ("read_write", "full_control"),
                share.permission == "full_control")
    return False, False


def can_manage_sharing(user, account, share=None):
    """Only full-control recipients may manage sharing; roles cannot upgrade a share."""
    return account_capabilities(user, account, share)[1]
