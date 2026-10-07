from services.transaction_lock import lock_mutation
import logging
import re
import uuid
from datetime import date as DateType, datetime, timezone, date as dt_date, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from services.request_validation import CurrencyCode
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select, func, or_

from database import get_session
from models import (
    Account, AccountShare, Family, User, Transaction, Transfer,
    Category, UserPreference
)
from auth import get_current_user_or_token, get_current_user
from services.card_sharing import primary_owner_can_read
from services.account_permissions import account_capabilities, can_manage_sharing
from services.account_types import normalize_account_type, account_classification, change_account_type, financial_classification
from services.card_settlement import group_for_account
from services.card_history import link_can_change

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/accounts", tags=["Accounts"])


def _hidden_sidebar_accounts(session: Session, user: Optional[User]) -> set:
    if user is None:
        return set()
    preferences = session.exec(select(UserPreference).where(UserPreference.username == user.username)).first()
    return set(preferences.hidden_sidebar_accounts or []) if preferences else set()


class AccountSidebarUpdate(BaseModel):
    hidden: bool
    confirm_nonzero_balance: bool = False


@router.patch("/{account_id}/sidebar")
def update_account_sidebar(
    account_id: uuid.UUID,
    payload: AccountSidebarUpdate,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Personal display preference, including accounts shared with read-only access."""
    lock_mutation(session)
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="用户未认证")
    account = session.get(Account, account_id)
    share = session.exec(select(AccountShare).where(
        AccountShare.account_id == account_id, AccountShare.user_id == user.id,
    )).first()
    if account is None or (user.family_id and account.family_id != user.family_id) or (
        account.owner_id != user.id and (not user.family_id or share is None)
    ):
        raise HTTPException(status_code=404, detail="Account not found")

    preferences = session.exec(select(UserPreference).where(UserPreference.username == username)).first()
    hidden = set(preferences.hidden_sidebar_accounts or []) if preferences else set()
    key = str(account.id)
    if payload.hidden and key not in hidden and not payload.confirm_nonzero_balance:
        balance = get_account_realtime_balance(
            session, account.id, account.classification, account.balance,
            current_user=user, cache_independently=True,
        )
        if balance != 0:
            raise HTTPException(status_code=409, detail={
                "code": "balance_confirmation_required",
                "balance": str(balance), "currency": account.currency,
            })

    if not preferences:
        preferences = UserPreference(username=username, date_format="DD/MM/YYYY", currency="CAD",
                                     has_chosen_currency=False, has_chosen_language=False)
    if payload.hidden:
        hidden.add(key)
    else:
        hidden.discard(key)
    preferences.hidden_sidebar_accounts = sorted(hidden)
    session.add(preferences)
    session.commit()
    return {"account_id": key, "hidden_in_sidebar": payload.hidden}


def _parent_account_summary(session: Session, account: Account):
    """Describe an existing card relationship without granting access to the parent."""
    if not account.parent_account_id:
        return None
    parent = session.get(Account, account.parent_account_id)
    if not parent or parent.family_id != account.family_id:
        return None
    owner = session.get(User, parent.owner_id) if parent.owner_id else None
    return {
        "id": str(parent.id),
        "name": parent.name,
        "account_type": parent.account_type,
        "currency": parent.currency,
        "owner_id": str(parent.owner_id) if parent.owner_id else None,
        "owner": (owner.display_name or owner.username) if owner else "未知用户",
    }


def _verify_account_management_permission(
    current_user: Optional[Any],
    account: Account,
    action_name: str = "管理该账户",
    session: Optional[Session] = None,
) -> bool:
    if isinstance(current_user, str) and current_user.startswith("service:"):
        from services.principals import verify_service_account
        verify_service_account(session, current_user, account)
        return True
    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")
    if account.family_id != getattr(current_user, "family_id", None):
        raise HTTPException(status_code=403, detail=f"无权{action_name}：该账户属于其他家庭")
    share = None
    if account.owner_id != current_user.id and session:
        share = session.exec(
            select(AccountShare).where(
                AccountShare.account_id == account.id,
                AccountShare.user_id == current_user.id,
            )
        ).first()
    _, can_manage = account_capabilities(current_user, account, share)
    if not can_manage:
        raise HTTPException(status_code=403, detail=f"只有账户拥有者或拥有完全控制权限的成员可以{action_name}")
    return True


def _calc_raw_account_balance(session: Session, account_id: uuid.UUID, classification: str = "asset", stored_balance: Optional[Decimal] = None) -> Decimal:
    """计算本账户全部活动的余额；期初活动与后续活动均只累计一次。

    未产生活动的账户可返回登记金额；已有活动只汇总账本，不回退旧基数。
    负债金额为流出减流入，资产金额为流入减流出。
    """
    from services.account_balances import raw_balance
    account = session.get(Account, account_id)
    if account is None:
        return stored_balance or Decimal("0.00")
    txns = session.exec(select(Transaction).where(Transaction.account_id == account_id)).all()
    return raw_balance(session, account, txns)


def _ensure_opening_balance_transaction(session: Session, account: Account) -> None:
    """把没有任何活动的账户期初金额记入流水；只在写操作中调用。"""
    if account.ledger_initialized:
        return
    opening = Decimal(str(account.balance or 0))
    if opening == 0:
        return
    if session.exec(select(Transaction.id).where(Transaction.account_id == account.id)).first():
        return
    is_liability = account.classification == "liability"
    transaction_type = "expense" if (opening > 0) == is_liability else "income"
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    session.add(Transaction(
        account_id=account.id,
        transacted_at=now.date(),
        occurred_at=now.astimezone(timezone.utc).replace(tzinfo=None),
        amount=abs(opening),
        currency=account.currency or "CNY",
        narration=f"{account.name} ({'期初欠款' if is_liability else '期初余额'})",
        transaction_type=transaction_type,
        category_source="manual",
        status="cleared",
        reconciled=True,
        excluded_from_stats=True,
        extra={"is_initial": True, "source": "account_opening"},
        notes="创建账户时期初余额自动生成交易明细记录",
    ))
    session.flush()


def get_account_realtime_balance(
    session: Session,
    account_id: uuid.UUID,
    classification: str = "asset",
    stored_balance: Optional[Decimal] = None,
    current_user: Optional[Any] = None,
    cache_independently: bool = False,
) -> Decimal:
    """
    依据真实交易明细严格计算账户当前数字：
    - 资产类账户 (asset):
      数字 = Σ(收入 + 退款 + 转入) - Σ(支出 + 转出)
    - 负债类账户 (liability):
      欠款 = Σ(消费/支出 expense) - Σ(还款/冲减 income + refund)
    - 信用卡主副卡统筹记账体系:
      1. 主卡 (Master Card): 承接全户综合账单，余额 = 全户总消费 - 全户总还款 (对齐银行月度总账单)
      2. 附属卡 (Child Card): 显示分摊还款后的待还金额，历史消费仍保留。
    """
    acc = session.get(Account, account_id)
    from services.account_balances import current_snapshot
    snapshot = current_snapshot(session, acc)
    if snapshot is not None:
        return snapshot.latest_balance
    if acc is not None and acc not in session.new and acc not in session.dirty and acc not in session.deleted:
        # A worker may retain this Session while another request unlinks or
        # reclassifies a card. Do not calculate using its old identity-map link.
        session.refresh(acc, attribute_names=['parent_account_id', 'account_type', 'classification',
                                             'family_id', 'currency', 'balance', 'ledger_initialized'])
    classification = financial_classification(acc) if acc else classification
    stored_balance = acc.balance if acc else stored_balance
    raw_bal = _calc_raw_account_balance(session, account_id, classification, stored_balance)

    if not acc:
        return raw_bal

    group = group_for_account(session, acc)
    if group:
        value = group.native_balance(acc.id) if group.master.id != acc.id else group.balance
        return -value if group.master.id == acc.id and classification == 'asset' else value
    return raw_bal


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    account_type: str = Field(default="checking", min_length=1, max_length=50)  # checking | savings | credit_card | investment | loan | other
    currency: CurrencyCode = "CNY"
    institution_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    external_identifier: Optional[str] = Field(default=None, max_length=100)
    balance: Optional[Decimal] = Field(default=Decimal("0"), max_digits=19, decimal_places=4)
    color: Optional[str] = None
    icon: Optional[str] = None
    parent_account_id: Optional[str] = None

    @field_validator('account_type', mode='before')
    @classmethod
    def validate_account_type(cls, value):
        return normalize_account_type(value)


class AccountUpdate(BaseModel):
    historical_settlement_policy: Optional[str] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    account_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    currency: Optional[CurrencyCode] = None
    institution_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    external_identifier: Optional[str] = Field(default=None, max_length=100)
    balance: Optional[Decimal] = Field(default=None, max_digits=19, decimal_places=4)
    color: Optional[str] = None
    icon: Optional[str] = None
    is_archived: Optional[bool] = None
    parent_account_id: Optional[str] = None

    @field_validator('account_type', mode='before')
    @classmethod
    def validate_account_type(cls, value):
        return normalize_account_type(value) if value is not None else None


class AccountShareMemberIn(BaseModel):
    user_id: uuid.UUID
    permission: str = "read_only"  # full_control | read_write | read_only
    shared: bool = True
    include_in_finances: Optional[bool] = True


class AccountSharesUpdate(BaseModel):
    members: Optional[List[AccountShareMemberIn]] = None
    update_finance_inclusion: Optional[bool] = None
    include_in_finances: Optional[bool] = None


class BulkAccountShareUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    user_id: uuid.UUID
    permission: Literal["read_only", "read_write", "full_control"] = "read_only"
    shared: bool = True


class BulkAccountSettingsUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    account_ids: List[uuid.UUID] = Field(min_length=1, max_length=200)
    hidden: Optional[bool] = None
    confirm_nonzero_balance: bool = False
    institution_name: Optional[str] = Field(default=None, max_length=100)
    account_type: Optional[Literal[
        "cash", "iou", "investment", "crypto", "real_estate", "vehicle", "other_asset",
        "credit_card", "loan", "other_liability", "checking", "savings", "other",
    ]] = None
    members: Optional[List[BulkAccountShareUpdate]] = Field(default=None, max_length=200)

    @field_validator('account_type', mode='before')
    @classmethod
    def validate_account_type(cls, value):
        return normalize_account_type(value) if value is not None else None


def _apply_account_share_updates(session, account, members):
    """Change only specified recipients, preserving each existing statistics preference."""
    for member in members:
        if member.user_id == account.owner_id:
            continue
        target = session.get(User, member.user_id)
        if not target or target.family_id != account.family_id:
            raise HTTPException(status_code=400, detail="无法共享给非本家庭成员")
        share = session.exec(select(AccountShare).where(
            AccountShare.account_id == account.id, AccountShare.user_id == member.user_id,
        )).first()
        if member.shared:
            if not share:
                share = AccountShare(account_id=account.id, user_id=member.user_id,
                                     permission=member.permission)
            else:
                share.permission = member.permission
            include = getattr(member, "include_in_finances", None)
            if include is not None:
                share.include_in_finances = include
            session.add(share)
        elif share:
            session.delete(share)


@router.patch("/bulk/settings")
def update_bulk_account_settings(
    payload: BulkAccountSettingsUpdate,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Validate the complete selection before changing any account; commit all changes together."""
    lock_mutation(session)
    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        raise HTTPException(401, "用户未认证")
    account_ids = list(dict.fromkeys(payload.account_ids))
    accounts = session.exec(select(Account).where(Account.id.in_(account_ids)).with_for_update()).all()
    shares = session.exec(select(AccountShare).where(
        AccountShare.account_id.in_(account_ids), AccountShare.user_id == user.id,
    )).all()
    my_shares = {share.account_id: share for share in shares}
    if len(accounts) != len(account_ids) or any(
        account.family_id != user.family_id
        or (account.owner_id != user.id and account.id not in my_shares)
        for account in accounts
    ):
        raise HTTPException(404, "Account not found")

    change_institution = "institution_name" in payload.model_fields_set
    change_information = change_institution or payload.account_type is not None
    change_sharing = bool(payload.members)
    if not change_information and not change_sharing and payload.hidden is None:
        raise HTTPException(400, "请选择要修改的设置")
    if change_information or change_sharing:
        for account in accounts:
            _verify_account_management_permission(user, account, "批量修改账户设置", session)
    if payload.members:
        member_ids = [member.user_id for member in payload.members]
        if len(set(member_ids)) != len(member_ids):
            raise HTTPException(400, "共享成员不能重复")
        targets = session.exec(select(User).where(User.id.in_(member_ids))).all()
        if len(targets) != len(member_ids) or any(target.family_id != user.family_id for target in targets):
            raise HTTPException(400, "无法共享给非本家庭成员")
    if payload.account_type and payload.account_type != "credit_card":
        child = session.exec(select(Account.id).where(Account.parent_account_id.in_(account_ids))).first()
        if child:
            raise HTTPException(400, "所选主卡仍有关联的副卡，无法修改为非信用卡类型")

    preferences = session.exec(select(UserPreference).where(UserPreference.username == username)).first()
    hidden = set(preferences.hidden_sidebar_accounts or []) if preferences else set()
    if payload.hidden and not payload.confirm_nonzero_balance:
        nonzero = []
        for account in accounts:
            if str(account.id) in hidden:
                continue
            balance = get_account_realtime_balance(session, account.id, account.classification,
                                                  account.balance, current_user=user)
            if balance != 0:
                nonzero.append({"account_id": str(account.id), "account_name": account.name,
                                "balance": str(balance), "currency": account.currency})
        if nonzero:
            raise HTTPException(409, {"code": "balance_confirmation_required", "accounts": nonzero})

    previous_parents = {account.id: account.parent_account_id for account in accounts}
    try:
        for account in accounts:
            if change_institution:
                account.institution_name = (payload.institution_name or "").strip() or None
            if payload.account_type:
                change_account_type(session, account, payload.account_type)
                if payload.account_type != "credit_card":
                    account.parent_account_id = None
            if change_information:
                account.updated_at = datetime.now(timezone.utc)
                session.add(account)
            if payload.members:
                _apply_account_share_updates(session, account, payload.members)
        if payload.hidden is not None:
            if not preferences:
                preferences = UserPreference(username=username, date_format="DD/MM/YYYY", currency="CAD",
                                             has_chosen_currency=False, has_chosen_language=False)
            if payload.hidden:
                hidden.update(str(account.id) for account in accounts)
            else:
                hidden.difference_update(str(account.id) for account in accounts)
            preferences.hidden_sidebar_accounts = sorted(hidden)
            session.add(preferences)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"status": "ok", "updated_count": len(accounts), "unlinked_account_ids": [
        str(account.id) for account in accounts
        if previous_parents[account.id] is not None and account.parent_account_id is None
    ]}


@router.get("")
@router.get("/")
def list_accounts(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取家庭名下所有可用资产与负债账户列表。
    支持按登录人角色与 AccountShare 授权过滤与增强展示。
    如果不共享某个账号，非 owner 且未被共享的成员将完全不可见此账户。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    from services.balance_sheet import visible_balance_accounts
    all_accounts = visible_balance_accounts(session, current_user or user_or_ctx)
    if not all_accounts:
        return {"accounts": [], "items": [], "count": 0}
    account_ids = {a.id for a in all_accounts}
    all_users = session.exec(select(User).where(User.id.in_({a.owner_id for a in all_accounts if a.owner_id}))).all()
    user_map = {u.id: (u.display_name or u.username) for u in all_users}
    owner_usernames = {u.id: u.username for u in all_users}

    # 获取全量共享记录
    all_shares = session.exec(select(AccountShare).where(AccountShare.account_id.in_(account_ids))).all()
    share_map: Dict[uuid.UUID, List[AccountShare]] = {}
    for s in all_shares:
        share_map.setdefault(s.account_id, []).append(s)

    # 统计每个账户名下的附属卡/子账户数量（用于标识主卡）
    child_counts = dict(
        session.exec(
            select(Account.parent_account_id, func.count(Account.id))
            .where(Account.parent_account_id.in_(account_ids))
            .group_by(Account.parent_account_id)
        ).all()
    )

    from services.report_currency import ReportCurrency
    report_money = ReportCurrency(session, current_user, cache_independently=True) if current_user else None
    from services.stats_engine import get_user_report_account_ids, get_report_account_balances
    report_ids = get_user_report_account_ids(session, current_user, current_user.family_id) if current_user else set()
    from services.account_balances import current_balances, own_settlement_balance
    native_balances = current_balances(session, all_accounts)
    report_own_balances = get_report_account_balances(session, all_accounts, report_money, native_balances) if report_money else {}
    hidden_sidebar_accounts = _hidden_sidebar_accounts(session, current_user)
    items = []
    for a in all_accounts:
        # 计算当前用户的权限与可见性：严格基于所有权与显式共享授权，绝无无感越权
        acc_shares = share_map.get(a.id, [])
        is_owner = current_user and a.owner_id == current_user.id
        my_share = next((s for s in acc_shares if current_user and s.user_id == current_user.id), None)

        # 核心隔离机制：账户默认私有，非所有人且未被共享的成员完全不可见
        if current_user and not is_owner and not my_share:
            continue

        # 卡号后4位提取
        mask_match = re.search(r"(\d{4})", a.name or "")
        mask = mask_match.group(1) if mask_match else (a.name[-4:] if len(a.name or "") >= 4 else "0000")
        owner_name = user_map.get(a.owner_id, "sliver")

        permission = "full_control" if is_owner else (my_share.permission if my_share else "read_only")
        can_edit, can_manage = account_capabilities(current_user, a, my_share)
        shared_with_count = len(acc_shares)

        realtime_bal = native_balances[a.id]
        own_settlement, settlement_currency = own_settlement_balance(session, a, realtime_bal)

        items.append({
            "id": str(a.id),
            "name": a.name,
            "mask": mask,
            "account_type": a.account_type,
            "classification": financial_classification(a),
            "currency": a.currency,
            "institution_name": a.institution_name,
            "external_identifier": a.external_identifier,
            "balance": str(realtime_bal),
            "report_balance": str(report_money.amount(realtime_bal, a.currency)) if report_money else str(realtime_bal),
            "report_settlement_balance": str(report_money.amount(own_settlement, settlement_currency)) if report_money else str(own_settlement),
            "report_own_balance": str(report_own_balances.get(a.id, 0)) if report_money else str(realtime_bal),
            "latest_balance": str(realtime_bal),
            "balance_version": a.balance_version,
            "balance_updated_at": a.balance_updated_at.isoformat() if a.balance_updated_at else None,
            "report_included": a.id in report_ids if current_user else not a.exclude_from_reports,
            "report_currency": report_money.currency if report_money else a.currency,
            "owner": owner_name,
            "owner_username": owner_usernames.get(a.owner_id, ""),
            "owner_id": str(a.owner_id) if a.owner_id else None,
            "transaction_count": a.latest_transaction_count,
            "is_active": getattr(a, "is_active", True),
            "hidden_in_sidebar": str(a.id) in hidden_sidebar_accounts,
            "is_owner": is_owner,
            "can_manage": can_manage,
            "can_manage_shares": can_manage_sharing(current_user, a, my_share),
            "can_edit": can_edit,
            "permission": permission,
            "shared_with_count": shared_with_count,
            "include_in_finances": my_share.include_in_finances if my_share else True,
            "parent_account_id": str(a.parent_account_id) if getattr(a, "parent_account_id", None) else None,
            "parent_account": _parent_account_summary(session, a),
            "card_link_can_change": link_can_change(session, a),
            "has_sub_accounts": a.id in child_counts,
            "sub_account_count": child_counts.get(a.id, 0),
        })

    from services.report_currency import persist_fx_cache
    persist_fx_cache(session)
    return {"accounts": items, "items": items, "count": len(items)}


@router.get("/shares/matrix")
def get_shares_matrix(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取家庭所有账户与成员的共享权限矩阵（供 Settings 设置界面一览并调整）。
    普通成员仅能管理自己拥有的账户或查看已共享给自己的账户。
    """
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if current_user and not current_user.family_id:
        return {"members": [], "accounts": [], "matrix": []}

    family = None
    if current_user and current_user.family_id:
        family = session.get(Family, current_user.family_id)
    else:
        family = session.exec(select(Family)).first()
    if not family:
        return {"members": [], "accounts": [], "matrix": []}

    members = session.exec(select(User).where(User.family_id == family.id)).all()
    if current_user:
        accounts = session.exec(
            select(Account).where(
                or_(
                    Account.family_id == family.id,
                    Account.owner_id == current_user.id,
                )
            )
        ).all()
    else:
        accounts = session.exec(select(Account).where(Account.family_id == family.id)).all()
    shares = session.exec(select(AccountShare)).all()

    shares_index = {(s.account_id, s.user_id): s for s in shares}

    matrix = []
    hidden_sidebar_accounts = _hidden_sidebar_accounts(session, current_user)
    for a in accounts:
        # 账户可见性只取决于所有权和显式共享，系统角色不授予私有账户访问权。
        is_my_account = current_user and a.owner_id == current_user.id
        has_share_to_me = current_user and ((a.id, current_user.id) in shares_index)
        if current_user and not is_my_account and not has_share_to_me:
            continue

        row_members = []
        for m in members:
            is_owner = (a.owner_id == m.id)
            share = shares_index.get((a.id, m.id))
            row_members.append({
                "user_id": str(m.id),
                "username": m.username,
                "display_name": m.display_name or m.username,
                "is_owner": is_owner,
                "shared": is_owner or (share is not None),
                "permission": "full_control" if is_owner else (share.permission if share else "read_only"),
                "include_in_finances": share.include_in_finances if share else True,
            })
        owner_member = next((m for m in members if m.id == a.owner_id), None)
        owner_name = (owner_member.display_name or owner_member.username) if owner_member else "我"
        my_share = shares_index.get((a.id, current_user.id)) if current_user else None
        _, can_manage = account_capabilities(current_user, a, my_share)
        matrix.append({
            "account_id": str(a.id),
            "account_name": a.name,
            "institution_name": a.institution_name,
            "external_identifier": a.external_identifier,
            "account_type": a.account_type,
            "balance": float(get_account_realtime_balance(
                session, a.id, a.classification, a.balance, current_user=current_user, cache_independently=True,
            )),
            "currency": a.currency,
            "owner_id": str(a.owner_id),
            "owner_name": owner_name,
            "can_manage": can_manage,
            "hidden_in_sidebar": str(a.id) in hidden_sidebar_accounts,
            "can_manage_shares": can_manage_sharing(current_user, a, my_share),
            "parent_account_id": str(a.parent_account_id) if a.parent_account_id else None,
            "parent_account": _parent_account_summary(session, a),
            "card_link_can_change": link_can_change(session, a),
            "members": row_members,
        })

    return {
        "family_id": str(family.id),
        "family_name": family.name,
        "members": [
            {"id": str(m.id), "username": m.username, "display_name": m.display_name or m.username, "role": m.role}
            for m in members
        ],
        "accounts": matrix,
    }


@router.get("/{account_id}/shares")
def get_account_shares(
    account_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取某具体账户的共享详情（对标 sure-web account_sharings/show）。
    """
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    shares = session.exec(select(AccountShare).where(AccountShare.account_id == account_id)).all()
    share_by_user = {s.user_id: s for s in shares}

    is_owner = current_user and current_user.id == account.owner_id
    is_same_family = current_user and current_user.family_id == account.family_id
    my_share = share_by_user.get(current_user.id) if current_user else None
    parent = session.get(Account, account.parent_account_id) if account.parent_account_id else None

    # 跨家庭访问直接拦截，管理员也必须遵循账户共享授权。
    if current_user and not is_same_family:
        raise HTTPException(status_code=403, detail="您无权查看其他家庭账户的共享设置")

    # 未被共享且非拥有者，禁止查看。
    if current_user and not is_owner and not my_share:
        raise HTTPException(status_code=403, detail="您无权查看此账户的共享设置")

    family_id = account.family_id
    all_members = session.exec(select(User).where(User.family_id == family_id)).all()
    owner = session.get(User, account.owner_id)

    can_manage = can_manage_sharing(current_user, account, my_share)

    members_data = []
    for m in all_members:
        if m.id == account.owner_id:
            continue  # Owner doesn't share with themselves
        sh = share_by_user.get(m.id)
        members_data.append({
            "user_id": str(m.id),
            "username": m.username,
            "display_name": m.display_name or m.username,
            "shared": sh is not None,
            "permission": sh.permission if sh else "read_only",
            "include_in_finances": sh.include_in_finances if sh else True,
        })

    my_share = share_by_user.get(current_user.id) if current_user else None

    return {
        "account_id": str(account.id),
        "account_name": account.name,
        "institution_name": account.institution_name,
        "external_identifier": account.external_identifier,
        "account_type": account.account_type,
        "balance": str(get_account_realtime_balance(session, account.id, account.classification, account.balance)),
        "card_link_can_change": link_can_change(session, account),
        "currency": account.currency,
        "is_owner": is_owner,
        "can_manage": can_manage,
        "parent_account_id": str(parent.id) if parent else None,
        "parent_account": _parent_account_summary(session, account),
        "parent_owner_id": str(parent.owner_id) if parent and parent.owner_id else None,
        "owner": {
            "id": str(owner.id) if owner else None,
            "username": owner.username if owner else "unknown",
            "display_name": (owner.display_name or owner.username) if owner else "未知用户",
        },
        "members": members_data,
        "my_share": {
            "shared": my_share is not None,
            "permission": my_share.permission if my_share else "read_only",
            "include_in_finances": my_share.include_in_finances if my_share else True,
        } if my_share else None,
    }


@router.patch("/{account_id}/shares")
@router.put("/{account_id}/shares")
def update_account_shares(
    account_id: uuid.UUID,
    payload: AccountSharesUpdate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    修改某账户对家庭成员的细粒度共享权限（对标 Sure PATCH account_sharing_path(@account)）。
    """
    lock_mutation(session)
    account = session.exec(select(Account).where(Account.id == account_id).with_for_update()).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    previous_parent_id = account.parent_account_id

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    management_share = session.exec(select(AccountShare).where(
        AccountShare.account_id == account_id, AccountShare.user_id == getattr(current_user, "id", None),
    )).first()
    can_manage = can_manage_sharing(current_user, account, management_share)

    # 1. 被共享人必须拥有完全控制才能管理共享；只读/读写仅可修改自己的统计偏好。
    if not can_manage:
        if payload.members is not None:
            raise HTTPException(status_code=403, detail="只有账户拥有者或拥有完全控制权限的成员才有权修改共享权限")
        if not current_user:
            raise HTTPException(status_code=403, detail="Permission denied")
        share = session.exec(
            select(AccountShare).where(
                AccountShare.account_id == account_id,
                AccountShare.user_id == current_user.id,
            )
        ).first()
        if not share:
            raise HTTPException(status_code=403, detail="You do not have access to this account")

        if payload.include_in_finances is not None:
            share.include_in_finances = payload.include_in_finances
            session.add(share)
            session.commit()
            return {"status": "ok", "include_in_finances": share.include_in_finances}
        return {"status": "ok", "message": "No changes requested"}

    # 2. 拥有管理权限的成员更新共享列表。
    if payload.include_in_finances is not None and management_share is not None:
        management_share.include_in_finances = payload.include_in_finances
        session.add(management_share)

    if payload.members is not None:
        _apply_account_share_updates(session, account, payload.members)

    if payload.members is not None or (payload.include_in_finances is not None and management_share is not None):
        session.commit()

    return {"status": "ok", "message": "Account shares updated successfully",
            "unlinked_from_parent": previous_parent_id is not None and account.parent_account_id is None}


@router.post("")
@router.post("/")
def create_account(
    data: AccountCreate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    创建新账户。
    """
    lock_mutation(session)
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    family = None
    if current_user and current_user.family_id:
        family = session.get(Family, current_user.family_id)
    elif current_user:
        # 未加入家庭的新用户创建账户，为其自动初始化属于其本人的专属家庭组并设为 owner
        family = Family(name=f"{current_user.display_name or current_user.username}的家庭", currency="CNY", kind="personal", personal_owner_user_id=current_user.id, is_solo=True)
        session.add(family)
        session.flush()
        current_user.family_id = family.id
        current_user.role = "owner"
        session.add(current_user)
        session.flush()
    else:
        from services.principals import service_family
        family = service_family(session)

    owner_id = current_user.id if current_user else None
    if not owner_id:
        owner = session.exec(select(User).where(User.family_id == family.id, User.is_active == True)).first()
        owner_id = owner.id if owner else None

    classification = account_classification(data.account_type)
    p_id = None
    if data.parent_account_id:
        if (data.account_type or "").lower() not in ("credit_card", "信用卡"):
            raise HTTPException(status_code=400, detail="只有信用卡类型支持设置主附卡关系")
        try:
            p_id = uuid.UUID(str(data.parent_account_id).strip())
            parent_acc = session.get(Account, p_id)
            if not parent_acc:
                raise HTTPException(status_code=400, detail="所选的主卡账户不存在")
            if parent_acc.family_id != family.id:
                raise HTTPException(status_code=403, detail="主附卡账户必须属于同一个家庭组")
            _verify_account_management_permission(current_user, parent_acc, "关联为主卡", session=session)
            if (parent_acc.account_type or "").lower() not in ("credit_card", "信用卡"):
                raise HTTPException(status_code=400, detail="主账户必须也是信用卡账户")
            if parent_acc.parent_account_id:
                raise HTTPException(status_code=400, detail="所选主账户自身已是副卡，不支持多级嵌套关联")
        except ValueError:
            raise HTTPException(status_code=400, detail="无效的主账户ID")

    account = Account(
        family_id=family.id,
        owner_id=owner_id,
        name=data.name,
        account_type=data.account_type,
        classification=classification,
        currency=data.currency,
        institution_name=data.institution_name,
        external_identifier=(data.external_identifier or "").strip() or None,
        balance=data.balance or Decimal("0"),
        color=data.color,
        icon=data.icon,
        parent_account_id=p_id,
    )
    if p_id and not primary_owner_can_read(session, account, parent_acc):
        raise HTTPException(status_code=400, detail="请先创建独立账户并共享给主卡所有者，再设置为副卡")
    session.add(account)
    session.flush()
    _ensure_opening_balance_transaction(session, account)
    session.commit()
    session.refresh(account)

    return {
        "id": str(account.id),
        "name": account.name,
        "account_type": account.account_type,
        "currency": account.currency,
        "institution_name": account.institution_name,
        "external_identifier": account.external_identifier,
        "balance": str(get_account_realtime_balance(session, account.id, classification, account.balance, current_user=current_user)),
        "color": account.color,
        "icon": account.icon,
        "parent_account_id": str(account.parent_account_id) if account.parent_account_id else None,
    }


class TransferOwnershipIn(BaseModel):
    new_owner_id: uuid.UUID


class ReconcileBalanceIn(BaseModel):
    new_balance: Decimal
    date: Optional[DateType] = None
    time: Optional[str] = None
    occurred_at: Optional[str] = None
    reconciliation_type: str = "adjustment"  # expense | income | transfer | adjustment
    name: Optional[str] = None
    category_id: Optional[str] = None
    counterparty_account_id: Optional[uuid.UUID] = None


@router.get("/{account_id}")
def get_account_detail(
    account_id: uuid.UUID,
    period: str = Query(default="MTD", description="Time period: MTD, 1M, 3M, 6M, YTD, ALL"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取单个账户详情与走势图表（对标 Sure 账户详情视图 ~/me/13.png）。
    """
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    all_users = session.exec(select(User)).all()
    user_map = {u.id: (u.display_name or u.username) for u in all_users}
    owner_name = user_map.get(account.owner_id, "sliver")

    shares = session.exec(select(AccountShare).where(AccountShare.account_id == account_id)).all()
    is_owner = current_user and current_user.id == account.owner_id
    my_share = next((s for s in shares if current_user and s.user_id == current_user.id), None)
    can_edit, can_manage = account_capabilities(current_user, account, my_share)

    # 权限隔离：严格基于所有权与显式共享授权，未被共享的成员完全不可见
    if current_user and account.family_id != current_user.family_id:
        raise HTTPException(status_code=403, detail="您无权查看其他家庭的账户")

    if current_user and not is_owner and not my_share:
        raise HTTPException(status_code=403, detail="您无权查看此账户")

    mask_match = re.search(r"(\d{4})", account.name or "")
    mask = mask_match.group(1) if mask_match else (account.name[-4:] if len(account.name or "") >= 4 else "0000")

    share_count = len(shares)
    is_me = current_user and current_user.id == account.owner_id
    prefix = "我的" if is_me else owner_name
    share_label = f"{prefix} · {'已共享' if share_count > 0 else '私有'}"

    # 计算时间范围走势图 (对标 13.png)
    from datetime import date, timedelta
    from models import Transaction

    try:
        tz_local = ZoneInfo("Asia/Shanghai")
    except Exception:
        tz_local = timezone.utc

    today = datetime.now(tz_local).date()
    if period == "MTD":
        start_date = today.replace(day=1)
    elif period == "1M":
        start_date = today - timedelta(days=30)
    elif period == "3M":
        start_date = today - timedelta(days=90)
    elif period == "6M":
        start_date = today - timedelta(days=180)
    elif period == "YTD":
        start_date = today.replace(month=1, day=1)
    else:
        start_date = dt_date(2020, 1, 1)

    # 查询该账户流水（若为主卡，级联穿透名下当前用户可见的附属卡明细）
    from services.balance_sheet import visible_balance_accounts
    accessible_acc_ids = {a.id for a in visible_balance_accounts(session, user_or_ctx if isinstance(user_or_ctx, str)
                          and user_or_ctx.startswith("service:") else current_user)}

    target_acc_ids = [account_id]
    if financial_classification(account) == "liability":
        children = session.exec(select(Account.id).where(Account.parent_account_id == account_id)).all()
        for cid in children:
            if cid in accessible_acc_ids:
                target_acc_ids.append(cid)

    txns = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(target_acc_ids),
            Transaction.transacted_at >= start_date,
            Transaction.transacted_at <= today,
        ).order_by(Transaction.transacted_at.asc())
    ).all()

    displayed = []
    for txn in txns:
        if txn.account_id != account.id:
            child = session.get(Account, txn.account_id)
            if txn.master_settlement_amount is not None or child.currency != account.currency:
                if txn.master_account_id != account.id or txn.master_settlement_amount is None:
                    raise HTTPException(409, "副卡流水缺少固定主卡结算金额")
                txn = txn.model_copy(update={"amount": txn.master_settlement_amount, "currency": account.currency})
        displayed.append(txn)
    txns = displayed

    realtime_bal = get_account_realtime_balance(session, account.id, financial_classification(account), account.balance, current_user=current_user, cache_independently=True)
    current_balance = float(realtime_bal)
    is_liability = financial_classification(account) == "liability"

    # 预加载 transfer 记录，用于判断每笔 transfer 的方向
    from models import Transfer as TransferModel
    tf_ids = [t.transfer_id for t in txns if t.transaction_type == "transfer" and t.transfer_id]
    tf_map: dict = {}
    if tf_ids:
        trs = session.exec(select(TransferModel).where(TransferModel.id.in_(tf_ids))).all()
        tf_map = {tr.id: tr for tr in trs}

    def is_transfer_outflow(t) -> bool:
        """判断该 transfer 交易是否为转出方（减少资产 / 增加负债债务）"""
        if t.transfer_id and t.transfer_id in tf_map:
            return t.id == tf_map[t.transfer_id].outflow_transaction_id
        if t.extra and isinstance(t.extra, dict) and t.extra.get("direction"):
            return t.extra.get("direction") == "outflow"
        # 孤立 transfer：按名称与账户类型判断
        hint = (t.narration or "") + (t.notes or "")
        inflow_kws = ["转入", "收到", "存入", "收款", "入账"]
        if is_liability:
            inflow_kws += ["还款", "扣缴", "偿还", "还清", "冲减", "结清"]
        elif getattr(account, "account_type", "") == "iou":
            inflow_kws += ["借据", "借出", "出具", "放款"]
        if any(kw in hint for kw in inflow_kws):
            return False
        return True

    # 模拟/计算估值点列表
    total_change = 0.0
    for t in txns:
        amt = float(t.amount)
        if is_liability:
            if t.transaction_type == "expense":
                total_change += amt
            elif t.transaction_type == "transfer":
                total_change += amt if is_transfer_outflow(t) else -amt
            elif t.transaction_type in ("income", "refund"):
                total_change -= amt
            elif t.transaction_type == "adjustment":
                is_decrease = False
                if t.extra and isinstance(t.extra, dict):
                    is_decrease = t.extra.get("direction") == "decrease"
                elif t.narration and "(-" in t.narration:
                    is_decrease = True
                total_change += -amt if is_decrease else amt
        else:
            if t.transaction_type == "expense":
                total_change -= amt
            elif t.transaction_type == "transfer":
                total_change += -amt if is_transfer_outflow(t) else amt
            elif t.transaction_type in ("income", "refund"):
                total_change += amt
            elif t.transaction_type == "adjustment":
                is_decrease = False
                if t.extra and isinstance(t.extra, dict):
                    is_decrease = t.extra.get("direction") == "decrease"
                elif t.narration and "(-" in t.narration:
                    is_decrease = True
                total_change += -amt if is_decrease else amt

    start_balance = current_balance - total_change
    if start_balance == 0:
        change_pct = 0.0
    else:
        change_pct = round(((current_balance - start_balance) / abs(start_balance)) * 100, 1)

    change_amount = round(current_balance - start_balance, 2)

    # 构建每日点
    days_count = (today - start_date).days + 1
    # 限制采样点数量在 10 ~ 30 之间
    step = max(1, days_count // 30)
    points = []
    running_bal = start_balance
    cur_d = start_date
    txn_idx = 0

    while cur_d <= today:
        while txn_idx < len(txns) and txns[txn_idx].transacted_at <= cur_d:
            t = txns[txn_idx]
            amt = float(t.amount)
            if is_liability:
                if t.transaction_type == "expense":
                    running_bal += amt
                elif t.transaction_type == "transfer":
                    running_bal += amt if is_transfer_outflow(t) else -amt
                elif t.transaction_type in ("income", "refund"):
                    running_bal -= amt
                elif t.transaction_type == "adjustment":
                    is_decrease = False
                    if t.extra and isinstance(t.extra, dict):
                        is_decrease = t.extra.get("direction") == "decrease"
                    elif t.narration and "(-" in t.narration:
                        is_decrease = True
                    running_bal += -amt if is_decrease else amt
            else:
                if t.transaction_type == "expense":
                    running_bal -= amt
                elif t.transaction_type == "transfer":
                    running_bal += -amt if is_transfer_outflow(t) else amt
                elif t.transaction_type in ("income", "refund"):
                    running_bal += amt
                elif t.transaction_type == "adjustment":
                    is_decrease = False
                    if t.extra and isinstance(t.extra, dict):
                        is_decrease = t.extra.get("direction") == "decrease"
                    elif t.narration and "(-" in t.narration:
                        is_decrease = True
                    running_bal += -amt if is_decrease else amt
            txn_idx += 1

        points.append({
            "date": cur_d.isoformat(),
            "label": cur_d.strftime("%b %d, %Y"),
            "balance": round(running_bal, 2)
        })
        cur_d += timedelta(days=step)

    # 确保包含今日终点
    if not points or points[-1]["date"] != today.isoformat():
        points.append({
            "date": today.isoformat(),
            "label": today.strftime("%b %d, %Y"),
            "balance": round(current_balance, 2)
        })

    card_group = group_for_account(session, account)
    own_balance = _calc_raw_account_balance(session, account.id, financial_classification(account), account.balance)
    repayment_allocations = []
    if card_group:
        own_balance = card_group.native_balance(account.id)
        if card_group.master.id == account.id and financial_classification(account) == 'asset':
            own_balance = -own_balance
        def card_balance_at(day):
            past = group_for_account(session, account, day)
            value = past.native_balance(account.id) if past.master.id != account.id else past.balance
            return -value if past.master.id == account.id and financial_classification(account) == 'asset' else value
        start_balance = float(card_balance_at(start_date - timedelta(days=1)))
        change_amount = round(current_balance - start_balance, 2)
        change_pct = round(change_amount / abs(start_balance) * 100, 1) if start_balance else 0.0
        points = [{**point, "balance": round(float(card_balance_at(dt_date.fromisoformat(point["date"]))), 2)}
                  for point in points]
        points[-1]["balance"] = round(current_balance, 2)
        # A secondary holder gets only their own allocations, never a private
        # primary/sibling transaction ID or the full payment amount.
        repayment_allocations = [
            {key: value for key, value in row.items() if key not in {"source_account_id", "account_id", "target_transaction_id"}}
            | {"source_transaction_id": row["source_transaction_id"] if uuid.UUID(row["source_account_id"]) in accessible_acc_ids else None}
            for row in card_group.allocations if row["account_id"] == str(account.id) and row["date"]
        ]

    from services.report_currency import persist_fx_cache
    persist_fx_cache(session)
    return {
        "account": {
            "id": str(account.id),
            "name": account.name,
            "mask": mask,
            "account_type": account.account_type,
            "classification": financial_classification(account),
            "institution_name": account.institution_name,
            "external_identifier": account.external_identifier,
            "currency": account.currency or "CNY",
            "balance": str(realtime_bal),
            "own_balance": str(own_balance),
            "subcard_settlement_balance": str(realtime_bal - own_balance) if not account.parent_account_id else "0",
            "balance_included": account.parent_account_id not in accessible_acc_ids,
            "is_settlement_primary": bool(card_group and card_group.master.id == account.id and len(card_group.cards) > 1),
            "owner": owner_name,
            "owner_id": str(account.owner_id) if account.owner_id else None,
            "is_owner": is_owner,
            "can_manage": can_manage,
            "can_manage_shares": can_manage_sharing(current_user, account, my_share),
            "can_edit": can_edit,
            "parent_account_id": str(account.parent_account_id) if account.parent_account_id else None,
            "parent_account": _parent_account_summary(session, account),
            "card_link_can_change": link_can_change(session, account),
            "shared_with_count": share_count,
            "share_label": share_label,
            "transaction_count": len(txns),
            "color": account.color,
            "icon": account.icon,
        },
        "metrics": {
            "balance": current_balance,
            "change_amount": change_amount,
            "change_percent": change_pct,
            "compare_label": "与月初相比" if period == "MTD" else "与期初相比",
        },
        "repayment_allocations": repayment_allocations,
        "chart": {
            "points": points,
            "start_date": start_date.strftime("%b %d, %Y"),
            "end_date": today.strftime("%b %d, %Y"),
            "start_iso": start_date.isoformat(),
            "end_iso": today.isoformat(),
        }
    }


@router.put("/{account_id}")
@router.patch("/{account_id}")
def update_account(
    account_id: uuid.UUID,
    data: AccountUpdate,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    更新账户信息（编辑账户）。
    """
    lock_mutation(session)
    account = session.exec(select(Account).where(Account.id == account_id).with_for_update()).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    current_user = None
    if isinstance(user_or_ctx, str) and not is_service:
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not is_service and current_user and current_user.role != "admin" and account.family_id != current_user.family_id:
        raise HTTPException(status_code=403, detail="无权编辑其他家庭名下的账户")
    _verify_account_management_permission(user_or_ctx if is_service else current_user,
                                         account, "修改账户信息", session=session)

    if data.is_archived is not None:
        account.is_active = not data.is_archived

    if data.name is not None:
        account.name = data.name.strip()
    if data.institution_name is not None:
        account.institution_name = data.institution_name.strip()
    if "external_identifier" in data.model_fields_set:
        account.external_identifier = (data.external_identifier or "").strip() or None
    if data.account_type is not None:
        new_type = data.account_type.strip()
        if new_type.lower() not in ("credit_card", "信用卡"):
            has_children = session.exec(select(Account).where(Account.parent_account_id == account.id)).first()
            if has_children:
                raise HTTPException(status_code=400, detail="该账户下仍有关联的附属卡，无法修改为非信用卡类型")
        change_account_type(session, account, new_type)
    if data.currency is not None:
        account.currency = data.currency.strip()
    if data.parent_account_id is not None:
        p_val = data.parent_account_id.strip()
        if p_val in ("", "none", "null"):
            account.parent_account_id = None
        else:
            if (account.account_type or "").lower() not in ("credit_card", "信用卡"):
                raise HTTPException(status_code=400, detail="只有信用卡类型支持设置主附卡关系")
            try:
                p_uuid = uuid.UUID(p_val)
                if p_uuid == account.id:
                    raise HTTPException(status_code=400, detail="不能将账户自身设为父账户")
                parent_acc = session.get(Account, p_uuid)
                if not parent_acc:
                    raise HTTPException(status_code=400, detail="所选的主卡账户不存在")
                if parent_acc.family_id != account.family_id:
                    raise HTTPException(status_code=403, detail="主附卡账户必须属于同一个家庭组")
                if p_uuid != account.parent_account_id:
                    _verify_account_management_permission(current_user, parent_acc, "关联为主卡", session=session)
                if (parent_acc.account_type or "").lower() not in ("credit_card", "信用卡"):
                    raise HTTPException(status_code=400, detail="主账户必须也是信用卡账户")
                if parent_acc.parent_account_id:
                    raise HTTPException(status_code=400, detail="所选主账户自身已是副卡，不支持多级嵌套关联")
                if not primary_owner_can_read(session, account, parent_acc):
                    raise HTTPException(status_code=400, detail="请先将此账户共享给主卡所有者，再设置为副卡")
                if session.exec(select(Account).where(Account.parent_account_id == account.id)).first():
                    raise HTTPException(status_code=400, detail="该账户已有副卡，不支持多级嵌套关联")
                if p_uuid != account.parent_account_id and parent_acc.currency != account.currency:
                    history = session.exec(select(Transaction.id).where(Transaction.account_id == account.id)).first()
                    if history and data.historical_settlement_policy != "convert_verified":
                        raise HTTPException(409, "绑定外币主卡需明确确认历史流水按交易日期固定结算，historical_settlement_policy=convert_verified")
                account.parent_account_id = p_uuid
            except ValueError:
                raise HTTPException(status_code=400, detail="无效的父账户ID")

    if data.balance is not None:
        classification = financial_classification(account)
        current_realtime = get_account_realtime_balance(session, account.id, classification, account.balance, current_user=current_user)
        target_balance = Decimal(str(data.balance))
        adjustment_time = datetime.now(timezone.utc)
        adjustment_day = adjustment_time.astimezone(ZoneInfo('Asia/Shanghai')).date()
        from services.card_settlement import balance_adjustment, adjustment_settlement
        diff = balance_adjustment(session, account, target_balance, current_realtime, adjustment_day)
        if diff != Decimal("0"):
            _ensure_opening_balance_transaction(session, account)
            # 编辑余额是调账，不能伪装成一笔真实消费或收入。
            adj_txn = Transaction(
                account_id=account.id,
                transacted_at=adjustment_day,
                occurred_at=adjustment_time.replace(tzinfo=None),
                amount=abs(diff),
                currency=account.currency or "CNY",
                narration=f"手动调整余额 ({'+' if diff > 0 else '-'}{abs(diff)})",
                transaction_type="adjustment",
                category_source="manual",
                status="cleared",
                reconciled=True,
                excluded_from_stats=True,
                extra={"diff": str(diff), "source": "account_edit", "direction": "increase" if diff > 0 else "decrease"},
                notes=f"手动修改余额自动生成交易明细: 原余额 {current_realtime} -> 新设定余额 {target_balance}",
                **adjustment_settlement(session, account, diff, adjustment_day),
            )
            session.add(adj_txn)

    if data.color is not None:
        account.color = data.color
    if data.icon is not None:
        account.icon = data.icon

    account.updated_at = datetime.now(timezone.utc)
    session.add(account)
    session.commit()
    session.refresh(account)

    return {
        "status": "ok",
        "account": {
            "id": str(account.id),
            "name": account.name,
            "institution_name": account.institution_name,
            "external_identifier": account.external_identifier,
            "account_type": account.account_type,
            "balance": str(get_account_realtime_balance(session, account.id, account.classification, account.balance, current_user=current_user)),
            "currency": account.currency,
            "color": account.color,
            "icon": account.icon,
            "parent_account_id": str(account.parent_account_id) if account.parent_account_id else None,
            "parent_account": _parent_account_summary(session, account),
        }
    }


@router.post("/{account_id}/transfer-ownership")
def transfer_account_ownership(
    account_id: uuid.UUID,
    data: TransferOwnershipIn,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    转移账户所有权给同一家庭的其他成员。
    """
    lock_mutation(session)
    account = session.exec(select(Account).where(Account.id == account_id).with_for_update()).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    _verify_account_management_permission(current_user, account, "转移所有权", session=session)

    new_owner = session.get(User, data.new_owner_id)
    if not new_owner or new_owner.family_id != account.family_id:
        raise HTTPException(status_code=400, detail="目标成员不存在或不在同一家庭组内")

    old_owner_id = account.owner_id
    account.owner_id = new_owner.id
    account.updated_at = datetime.now(timezone.utc)
    session.add(account)

    # 原所有者保留完全控制共享权限
    if old_owner_id and old_owner_id != new_owner.id:
        existing_share = session.exec(
            select(AccountShare).where(AccountShare.account_id == account_id, AccountShare.user_id == old_owner_id)
        ).first()
        if not existing_share:
            new_share = AccountShare(
                account_id=account_id,
                user_id=old_owner_id,
                permission="full_control",
                include_in_finances=True,
            )
            session.add(new_share)
        else:
            existing_share.permission = "full_control"
            session.add(existing_share)

    # 移除新所有者原有的 share 记录
    new_owner_share = session.exec(
        select(AccountShare).where(AccountShare.account_id == account_id, AccountShare.user_id == new_owner.id)
    ).first()
    if new_owner_share:
        session.delete(new_owner_share)

    session.commit()
    return {"status": "ok", "message": f"所有权已成功转移给 {new_owner.display_name or new_owner.username}"}


@router.delete("/{account_id}")
def delete_account(
    account_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    删除或归档账户（级联清理关联子卡、估值、贷款、交易与共享）。
    """
    lock_mutation(session)
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    current_user = None
    if isinstance(user_or_ctx, str) and not is_service:
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    _verify_account_management_permission(user_or_ctx if is_service else current_user, account, "删除该账户", session=session)
    from services.financial_deletion import delete_account_data
    delete_account_data(session, {account_id})
    session.commit()
    return {"status": "ok", "message": "账户已成功删除"}


@router.post("/{account_id}/reconcile-balance")
def reconcile_balance(
    account_id: uuid.UUID,
    payload: ReconcileBalanceIn,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    确认新余额与差额对账（严格对标 Sure 逻辑 ~/me/14.png）：
    - 支出 (expense): 生成支出交易
    - 收入 (income): 生成收入交易
    - 转账 (transfer): 生成转账交易
    - 仅调整余额 (adjustment): 直接修改余额，不产生日常收支消费
    """
    lock_mutation(session)
    from datetime import date as dt_date
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
    current_user = None
    if isinstance(user_or_ctx, str) and not is_service:
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not is_service:
        if not current_user:
            raise HTTPException(status_code=401, detail="用户未认证")

        is_admin = current_user.role == "admin"
        if not is_admin and account.family_id != current_user.family_id:
            raise HTTPException(status_code=403, detail="无权操作其他家庭的账户")

        is_owner = current_user.id == account.owner_id
        share = session.exec(
            select(AccountShare).where(AccountShare.account_id == account_id, AccountShare.user_id == current_user.id)
        ).first()
        can_edit, _ = account_capabilities(current_user, account, share)

        if not can_edit:
            raise HTTPException(status_code=403, detail="您没有权限为此账户调整余额")

    if payload.reconciliation_type == "transfer" and payload.counterparty_account_id:
        from routes.v1_transactions import _verify_account_write_permission
        counterparty = session.get(Account, payload.counterparty_account_id)
        if not counterparty or counterparty.family_id != account.family_id:
            raise HTTPException(status_code=400, detail="转账对端账户不存在或属于其他家庭")
        if counterparty.id == account.id:
            raise HTTPException(status_code=400, detail="转账对端不能是同一账户")
        if counterparty.currency != account.currency:
            raise HTTPException(status_code=400, detail="跨币种转账需要明确兑换金额，当前不支持")
        _verify_account_write_permission(session, user_or_ctx, counterparty.id, "转账对账")

    classification = financial_classification(account)
    current_balance = get_account_realtime_balance(session, account.id, classification, account.balance, current_user=current_user)
    old_balance = current_balance
    new_balance = Decimal(str(payload.new_balance if payload.new_balance is not None else old_balance))
    diff = new_balance - old_balance
    try:
        tz_local = ZoneInfo("Asia/Shanghai")
    except Exception:
        tz_local = timezone.utc
    tx_date = payload.date if payload.date else datetime.now(tz_local).date()
    from services.card_settlement import balance_adjustment
    diff = balance_adjustment(session, account, new_balance, old_balance, tx_date)
    tx_occurred_at = None
    if payload.occurred_at:
        try:
            from datetime import datetime as dt_datetime
            tx_occurred_at = dt_datetime.fromisoformat(payload.occurred_at)
        except Exception:
            pass
    if not tx_occurred_at and payload.time:
        try:
            from datetime import time as dt_time, datetime as dt_datetime
            parts = [int(p) for p in payload.time.strip().split(":")]
            if len(parts) == 3:
                tx_occurred_at = dt_datetime.combine(tx_date, dt_time(parts[0], parts[1], parts[2]))
            elif len(parts) == 2:
                tx_occurred_at = dt_datetime.combine(tx_date, dt_time(parts[0], parts[1], 0))
        except Exception:
            pass
    if not tx_occurred_at:
        from datetime import datetime as dt_datetime
        tx_occurred_at = dt_datetime.combine(tx_date, dt_datetime.now(tz_local).time())
    if tx_occurred_at.tzinfo is None:
        tx_occurred_at = tx_occurred_at.replace(tzinfo=tz_local)
    tx_occurred_at = tx_occurred_at.astimezone(timezone.utc).replace(tzinfo=None)

    created_txn = None
    VALID_RECON_TYPES = {"expense", "income", "transfer", "adjustment"}
    if payload.reconciliation_type not in VALID_RECON_TYPES:
        raise HTTPException(status_code=400, detail=f"reconciliation_type 必须是 {sorted(VALID_RECON_TYPES)} 之一")

    if payload.reconciliation_type in ("expense", "income") and diff != Decimal("0"):
        expected_type = "expense" if (diff > 0) == (classification == "liability") else "income"
        if payload.reconciliation_type != expected_type:
            raise HTTPException(status_code=400, detail=f"该余额变化应选择 {expected_type}，或使用余额调整")

    if diff != Decimal("0"):
        _ensure_opening_balance_transaction(session, account)

    if payload.reconciliation_type in ("expense", "income") and diff != Decimal("0"):
        amt = abs(diff)
        from services.rules.categories import resolve_category, other_category
        cat_id = other_category(session, account.family_id, create=True).id
        if payload.category_id:
            try:
                cat_id = resolve_category(session, payload.category_id, account.family_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

        txn_name = payload.name or ("余额对账支出" if payload.reconciliation_type == "expense" else "余额对账收入")
        txn = Transaction(
            account_id=account.id,
            transacted_at=tx_date,
            occurred_at=tx_occurred_at,
            amount=amt,
            currency=account.currency or "CNY",
            narration=txn_name,
            transaction_type=payload.reconciliation_type,
            category_id=cat_id,
            category_source="manual",
            status="cleared",
            reconciled=True,
            notes=f"新余额对账生成: 原余额 {old_balance} -> 新余额 {new_balance}",
        )
        session.add(txn)
        session.flush()
        created_txn = str(txn.id)

    elif payload.reconciliation_type == "transfer" and diff != Decimal("0"):
        amt = abs(diff)
        if classification == "liability":
            is_inflow = (diff < 0)  # 负债减少为资金转入还款，负债增加为转出透支
        else:
            is_inflow = (diff > 0)  # 资产增加为资金转入，资产减少为资金转出

        direction_desc = "转入" if is_inflow else "转出"
        default_name = f"余额对账{direction_desc} ({'+' if is_inflow else '-'}{amt})"
        txn_name = payload.name or default_name
        if is_inflow and "转入" not in txn_name:
            txn_name = f"{txn_name} (转入)"
        elif not is_inflow and "转出" not in txn_name:
            txn_name = f"{txn_name} (转出)"

        c_acc = None
        if payload.counterparty_account_id:
            c_acc = session.get(Account, payload.counterparty_account_id)
            if not c_acc or c_acc.family_id != account.family_id:
                raise HTTPException(status_code=400, detail="指定的转账对端账户不存在或属于其他家庭")

        txn = Transaction(
            account_id=account.id,
            transacted_at=tx_date,
            occurred_at=tx_occurred_at,
            amount=amt,
            currency=account.currency or "CNY",
            narration=txn_name,
            transaction_type="transfer",
            category_source="manual",
            status="cleared",
            reconciled=True,
            extra={"direction": "inflow" if is_inflow else "outflow", "diff": str(diff), "external_transfer": c_acc is None},
            notes=f"新余额转账生成: 对端账户 {payload.counterparty_account_id}",
        )
        session.add(txn)
        session.flush()

        if c_acc:
            c_is_inflow = not is_inflow
            c_name = f"收到{account.name}转入" if c_is_inflow else f"转出到{account.name}"
            c_txn = Transaction(
                account_id=c_acc.id,
                transacted_at=tx_date,
                occurred_at=tx_occurred_at,
                amount=amt,
                currency=c_acc.currency or account.currency or "CNY",
                narration=c_name,
                transaction_type="transfer",
                category_source="manual",
                status="cleared",
                reconciled=True,
                extra={"direction": "inflow" if c_is_inflow else "outflow"},
                notes=f"对账转账关联: 来自账户 {account.name}",
            )
            session.add(c_txn)
            session.flush()

            out_id = c_txn.id if is_inflow else txn.id
            in_id = txn.id if is_inflow else c_txn.id
            transfer_record = Transfer(
                family_id=account.family_id,
                outflow_transaction_id=out_id,
                inflow_transaction_id=in_id,
                amount=amt,
                status="confirmed",
            )
            session.add(transfer_record)
            session.flush()
            txn.transfer_id = transfer_record.id
            c_txn.transfer_id = transfer_record.id
            session.add(txn)
            session.add(c_txn)

        created_txn = str(txn.id)

    elif payload.reconciliation_type == "adjustment" and diff != Decimal("0"):
        from services.card_settlement import adjustment_settlement
        amt = abs(diff)
        direction = "increase" if diff > 0 else "decrease"
        txn_name = payload.name or f"余额对账调整 ({'+' if diff > 0 else '-'}{amt})"
        txn = Transaction(
            account_id=account.id,
            transacted_at=tx_date,
            occurred_at=tx_occurred_at,
            amount=amt,
            currency=account.currency or "CNY",
            narration=txn_name,
            transaction_type="adjustment",
            category_source="manual",
            status="cleared",
            reconciled=True,
            excluded_from_stats=True,
            extra={"direction": direction, "diff": str(diff)},
            notes=f"新余额对账调整生成: 原余额 {old_balance} -> 新余额 {new_balance}",
            **adjustment_settlement(session, account, diff, tx_date),
        )
        session.add(txn)
        session.flush()
        created_txn = str(txn.id)

    # 对账只追加活动，不把最新余额写回期初基数。
    account.updated_at = datetime.now(timezone.utc)
    session.add(account)
    session.commit()
    session.refresh(account)

    return {
        "status": "ok",
        "new_balance": str(get_account_realtime_balance(session, account.id, classification, account.balance, current_user=current_user)),
        "difference": str(diff),
        "reconciliation_type": payload.reconciliation_type,
        "transaction_id": created_txn,
    }
