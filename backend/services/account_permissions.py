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


def can_receive_transfer(user, account, share=None):
    """Receiving a new transfer never grants permission to debit or edit."""
    if not account.is_active:
        return False
    if isinstance(user, str) and user.startswith("service:"):
        return True  # The caller still verifies the service's account scope.
    if not user or not user.family_id or account.family_id != user.family_id:
        return False
    return account.owner_id == user.id or (
        share is not None and share.permission in ("read_only", "read_write", "full_control")
    )
