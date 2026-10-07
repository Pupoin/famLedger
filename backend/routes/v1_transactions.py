from services.transaction_lock import lock_mutation
import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, select, func, desc, asc, or_

from database import get_session
from models import (
    Account,
    AccountShare,
    Category,
    Family,
    RefundAllocation,
    RejectedTransfer,
    Rule,
    Transaction,
    TransactionSplit,
    Transfer,
    User,
)
from auth import get_current_user_or_token
from services.rules.pipeline import RulePipeline
from services.booking_money import PendingExchangeRate, prepare_booking, money_metadata, money_text
from services.request_validation import CurrencyCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/transactions", tags=["Transactions"])


def clean_to_utc(v: Any, default_tz_name: str = "Asia/Shanghai") -> Optional[datetime]:
    """
    通用时间清洗切面拦截器：
    无论输入是标准 UTC 字符串（含 Z）、带偏移字符串（+08:00）、裸字符串（2026-09-29 23:42:58）还是 datetime，
    统一转换为带有 timezone.utc 的标准 datetime。
    """
    if v is None or v == "":
        return None
    try:
        tz_local = ZoneInfo(default_tz_name)
    except Exception:
        tz_local = timezone.utc

    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            try:
                dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            except Exception:
                raise ValueError("交易时间格式无效")
    elif isinstance(v, datetime):
        dt = v
    elif isinstance(v, date):
        dt = datetime.combine(v, datetime.min.time())
    else:
        raise ValueError("交易时间必须为日期或时间字符串")

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    else:
        # 无时区标识（naive datetime），默认视作用户本地业务时区解释
        return dt.replace(tzinfo=tz_local).astimezone(timezone.utc)


def get_local_date(utc_dt: datetime, default_tz_name: str = "Asia/Shanghai") -> date:
    """从 UTC datetime 获取对应的本地业务自然日。"""
    try:
        tz_local = ZoneInfo(default_tz_name)
    except Exception:
        tz_local = timezone.utc
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(tz_local).date()


def serialize_utc_datetime(dt: Optional[datetime]) -> Optional[str]:
    """统一将数据库中的时间字段序列化为带有 Z 标记的标准 ISO 8601 UTC 字符串。"""
    if not dt:
        return None
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}Z"


class TransactionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    account: Optional[str] = None
    occurred_at: Optional[datetime] = None
    amount: Decimal = Field(..., gt=Decimal("0"), max_digits=19, decimal_places=4)
    currency: Optional[CurrencyCode] = None
    original_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    original_currency: Optional[CurrencyCode] = None
    settlement_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    settlement_currency: Optional[CurrencyCode] = None
    settlement_source: str = "bank"
    master_settlement_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    master_settlement_currency: Optional[CurrencyCode] = None
    refund_original_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    allocation_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    allocation_currency: Optional[CurrencyCode] = None
    narration: str = Field(max_length=255)
    category_id: Optional[uuid.UUID] = None
    category_name: Optional[str] = None
    transaction_type: Optional[str] = "expense"  # expense | income | transfer | refund
    external_id: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
    extra: Optional[Dict[str, Any]] = None
    refund_of_transaction_id: Optional[uuid.UUID] = None
    date: Optional[str] = None
    transacted_at: Optional[Any] = None
    time: Optional[str] = None

    @field_validator("occurred_at", mode="before")
    @classmethod
    def validate_occurred_at(cls, v: Any):
        return clean_to_utc(v)

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[Any] = None,
    ) -> "TransactionIn":
        # 兼容旧调用输入映射
        if isinstance(obj, dict):
            obj = dict(obj)
            if "narration" not in obj:
                obj["narration"] = obj.get("name") or obj.get("merchant_name") or "未命名交易"
            if "account" not in obj:
                obj["account"] = obj.get("account_id") or obj.get("account_identifier")
            if "refund_of_transaction_id" not in obj and obj.get("original_transaction_id"):
                obj["refund_of_transaction_id"] = obj.get("original_transaction_id")
            if not obj.get("occurred_at") and (obj.get("transacted_at") or obj.get("date")):
                t_date = str(obj.get("transacted_at") or obj.get("date")).strip()
                t_time = str(obj.get("time") or "00:00:00").strip()
                if len(t_time.split(":")) == 2:
                    t_time += ":00"
                obj["occurred_at"] = f"{t_date}T{t_time}"
            if "transaction_type" not in obj and obj.get("nature"):
                nat = str(obj.get("nature"))
                if nat in ("refund", "退款", "退货", "消费撤销"):
                    obj["transaction_type"] = "refund"
                elif nat in ("income", "收入"):
                    obj["transaction_type"] = "income"
                elif nat in ("transfer", "转账"):
                    obj["transaction_type"] = "transfer"
                else:
                    obj["transaction_type"] = "expense"
            # 兼容旧顶级 counterparty 收敛进 extra
            ext = dict(obj.get("extra") or {})
            if "counterparty" in obj and obj["counterparty"]:
                ext.setdefault("counterparty", obj["counterparty"])
            if ext:
                obj["extra"] = ext
        return super().model_validate(
            obj,
            strict=strict,
            from_attributes=from_attributes,
            context=context,
        )

    @classmethod
    def parse_obj(cls, obj: Any) -> "TransactionIn":
        return cls.model_validate(obj)


def _resolve_account(session: Session, family_id: uuid.UUID, identifier: str, user_or_ctx: Any = None) -> Account:
    """UUID, then exact external ID, then unconfigured account names; reject ambiguity."""
    raw_str = identifier.strip()

    # 1. 尝试以 UUID 嗅探查找（内部系统主键直接命中）
    try:
        acc_uuid = uuid.UUID(raw_str)
        acc = session.get(Account, acc_uuid)
        if acc:
            return acc
    except (ValueError, TypeError, AttributeError):
        pass

    accounts = session.exec(select(Account).where(Account.family_id == family_id)).all()

    # 2. Parse a bank-qualified identifier or a standalone four-digit card suffix.
    institution, last4 = None, raw_str
    if ":" in raw_str:
        parts = [p.strip() for p in raw_str.split(":", 1)]
        institution, last4 = parts[0], parts[1]
    elif "-" in raw_str and not raw_str.startswith("-"):
        parts = [p.strip() for p in raw_str.split("-", 1)]
        institution, last4 = parts[0], parts[1]
    elif " " in raw_str:
        parts = raw_str.rsplit(None, 1)
        institution, last4 = parts[0].strip(), parts[1].strip()

    num_match = re.search(r"(?<!\d)(\d{4})(?!\d)", last4)
    target_digits = num_match.group(1) if num_match else last4

    hint = raw_str.casefold()
    credit_types = {"credit_card", "credit", "信用卡"}
    debit_types = {"checking", "savings", "cash", "debit_card", "debit", "借记卡", "储蓄卡", "现金"}
    card_type = "credit" if any(k in hint for k in ("信用卡", "credit_card", "credit card")) else (
        "debit" if any(k in hint for k in ("借记卡", "储蓄卡", "debit_card", "debit card")) else None
    )

    def institution_label(value):
        return re.sub(
            r"信用卡|借记卡|储蓄卡|credit[_ ]card|debit[_ ]card", "",
            (value or "").strip(), flags=re.IGNORECASE,
        ).strip()

    def bank_label(value):
        return institution_label(value).casefold()

    bank = bank_label(institution)

    def eligible(acc):
        kind = (acc.account_type or "").casefold()
        if card_type == "credit" and kind not in credit_types:
            return False
        if card_type == "debit" and kind not in debit_types:
            return False
        if bank:
            stored_bank = bank_label(acc.institution_name or acc.name)
            return bool(stored_bank) and (bank in stored_bank or stored_bank in bank)
        return True

    def single_match(candidates):
        if len(candidates) > 1:
            raise HTTPException(status_code=409, detail="多个账户匹配此银行、卡类型和标识，请使用账户 UUID 或修改外部账户标识")
        return candidates[0] if candidates else None

    # The full source identifier is authoritative, independent of display metadata.
    exact = single_match([acc for acc in accounts if acc.external_identifier and
                          acc.external_identifier.strip() == raw_str])
    if exact:
        return exact

    candidates = [acc for acc in accounts if eligible(acc)]
    # A suffix-only identifier is less specific and must also match bank and type.
    if re.fullmatch(r"\d{4}", target_digits):
        suffix_match = single_match([acc for acc in candidates if acc.external_identifier and
                                     acc.external_identifier.strip() == target_digits])
        if suffix_match:
            return suffix_match

    # Only accounts without an external identifier may use their display name.
    unconfigured = [acc for acc in candidates if not (acc.external_identifier or "").strip()]
    # A full display name is also an explicit selector. Bank-qualified imports
    # retain the bank/type filters; spaces in a user alias are not a bank name.
    exact_name = single_match([acc for acc in accounts if
                              not (acc.external_identifier or "").strip() and acc.name == raw_str and
                              (eligible(acc) or (":" not in raw_str and "-" not in raw_str))])
    if exact_name:
        return exact_name
    suffix_pattern = rf"(?<!\d){re.escape(target_digits)}(?!\d)" if re.fullmatch(r"\d{4}", target_digits) else None
    by_name = single_match([acc for acc in unconfigured if (
        re.search(suffix_pattern, acc.name) if suffix_pattern else target_digits in acc.name
    )])
    if by_name:
        return by_name

    # 4. No match: retain the complete POST selector independently of the alias.
    if len(raw_str) > 100:
        raise HTTPException(status_code=422, detail="外部账户标识不能超过 100 个字符")
    is_credit = card_type == "credit"
    acc_type = "credit_card" if is_credit else "checking"
    bank_name = institution_label(institution) or None
    acc_name = f"{bank_name} {target_digits}" if bank_name else raw_str

    current_u = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_u = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if current_u and current_u.family_id != family_id and current_u.role != "admin":
        raise HTTPException(status_code=403, detail="无权在该家庭组下自动预拨账户")

    owner_id = current_u.id if current_u else None
    if not owner_id:
        owner = session.exec(select(User).where(User.family_id == family_id)).first()
        owner_id = owner.id if owner else None

    new_acc = Account(
        family_id=family_id,
        owner_id=owner_id,
        name=acc_name,
        account_type=acc_type,
        classification="liability" if is_credit else "asset",
        currency="CNY",
        institution_name=bank_name,
        external_identifier=raw_str,
    )
    session.add(new_acc)
    session.flush()
    logger.info("自动预拨新账户(暂存): id=%s name=%s bank=%s", new_acc.id, new_acc.name, bank_name)
    return new_acc


def _verify_account_write_permission(
    session: Session,
    user_or_ctx: Any,
    account_id: uuid.UUID,
    action_desc: str = "操作交易",
):
    """
    通用账户写权限校验器：
    账户所有者可写；共享成员须具有 read_write 或 full_control。
    显式只读共享同样限制管理员；没有显式共享时保留系统管理权限。
    普通用户必须属于账户所在家庭。
    """
    if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"):
        from services.principals import verify_service_account
        account = session.get(Account, account_id)
        if not account:
            raise HTTPException(404, "账户不存在")
        verify_service_account(session, user_or_ctx, account)
        return

    current_user = None
    if isinstance(user_or_ctx, str):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")

    if account.family_id != current_user.family_id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail=f"无权{action_desc}：该账户属于其他家庭")

    if account.owner_id == current_user.id:
        return

    share = session.exec(
        select(AccountShare).where(
            AccountShare.account_id == account.id,
            AccountShare.user_id == current_user.id,
        )
    ).first()

    from services.account_permissions import account_capabilities
    can_write, _ = account_capabilities(current_user, account, share)
    if not can_write:
        raise HTTPException(status_code=403, detail=f"您没有此账户的写入权限，无法{action_desc}")


def _verify_account_read_permission(
    session: Session,
    user_or_ctx: Any,
    account_id: uuid.UUID,
    action_desc: str = "查看交易",
):
    """
    通用账户读权限校验器：
    1. 系统超级管理员 (admin) 具备全局读权限；
    2. 严格校验账户属于当前用户的 family_id；
    3. 账户创建者 / 所有者具备读权限；
    4. 被共享用户具备读权限；
    5. 其他无权用户抛出 403。
    """
    if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"):
        from services.principals import verify_service_account
        account = session.get(Account, account_id)
        if not account:
            raise HTTPException(404, "账户不存在")
        verify_service_account(session, user_or_ctx, account)
        return

    current_user = None
    if isinstance(user_or_ctx, str):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="用户未认证")

    if current_user.role == "admin":
        return

    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="账户不存在")

    if account.family_id != current_user.family_id:
        raise HTTPException(status_code=403, detail=f"无权{action_desc}：该账户属于其他家庭")

    if account.owner_id == current_user.id:
        return

    share = session.exec(
        select(AccountShare).where(
            AccountShare.account_id == account.id,
            AccountShare.user_id == current_user.id,
        )
    ).first()

    if not share:
        raise HTTPException(status_code=403, detail=f"该账户未向您共享，无权{action_desc}")


@router.post("")
@router.post("/")
async def create_or_ingest_transaction(
    request: Request,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    创建或批量录入单笔交易流水（精炼规范）。
    唯一时间源 occurred_at，商户描述 narration，支持 account (UUID 或 银行:尾号)。
    自动触发转账撮合与退款抵消。
    """
    from services.request_validation import parse_body
    data = await parse_body(request, TransactionIn, "transaction")
    result = ingest_transaction(data, session, user_or_ctx)
    session.commit()
    return result


def ingest_transaction(data, session, user_or_ctx, pending_record=None):
    lock_mutation(session)
    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    family_id = current_user.family_id if current_user else None
    if not family_id:
        if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"):
            from services.principals import service_family
            first_fam = service_family(session)
            family_id = first_fam.id if first_fam else None
        elif current_user:
            # 未加入家庭的用户，为其自动创建属于自己的专属家庭组
            new_fam = Family(name=f"{current_user.display_name or current_user.username}的家庭", currency="CNY", kind="personal", personal_owner_user_id=current_user.id, is_solo=True)
            session.add(new_fam)
            session.flush()
            session.refresh(new_fam)
            current_user.family_id = new_fam.id
            current_user.role = "owner"
            session.add(current_user)
            session.flush()
            family_id = new_fam.id

    if not family_id:
        raise HTTPException(status_code=400, detail="您尚未加入家庭组，无法记录交易流水")

    # 1. 确定账户
    account_key = data.account or "default"
    account = _resolve_account(session, family_id, str(account_key), user_or_ctx=user_or_ctx)

    # 1.1 校验当前用户对该账户的写权限 (read_only / unshared 拦截)
    _verify_account_write_permission(session, user_or_ctx, account.id, "记账")
    family_id = account.family_id

    # 2. 确定交易精确时间与记账自然日（occurred_at 已由切面保证为标准 UTC 时间）
    occurred_at_utc = data.occurred_at or datetime.now(timezone.utc)
    transacted_date = get_local_date(occurred_at_utc)
    occurred_at_clean = occurred_at_utc.replace(tzinfo=None)

    # 3. 确定交易方向与类型
    txn_type = data.transaction_type or "expense"
    if txn_type not in ("expense", "income", "transfer", "refund"):
        raise HTTPException(422, "不支持的交易类型")

    # 金额统一规范化（绝对值正数存储，transaction_type 区分属性）
    amount = abs(Decimal(str(data.amount)))
    if amount <= Decimal("0"):
        raise HTTPException(status_code=400, detail="交易金额必须大于 0")

    # 4. 幂等去重校验 (account_id + external_id)
    if data.external_id:
        existing = session.exec(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.external_id == data.external_id,
            )
        ).first()
        if existing:
            if pending_record is not None:
                pending_record.status = "posted"
                pending_record.posted_transaction_id = existing.id
                pending_record.last_error = None
                session.add(pending_record)
            return {
                "id": str(existing.id),
                "account_id": str(existing.account_id),
                "external_id": existing.external_id,
                "status": "duplicate",
                "message": "Transaction already ingested",
            }

    from services.schedules import reconcile_import
    scheduled_match = reconcile_import(session, user_or_ctx, account, data, transacted_date)
    if scheduled_match:
        return scheduled_match

    from models import PendingFxTransaction
    if data.external_id and pending_record is None:
        saved = session.exec(select(PendingFxTransaction).where(
            PendingFxTransaction.account_id == account.id, PendingFxTransaction.external_id == data.external_id)).first()
        if saved:
            from routes.v1_pending_fx import serialize_pending
            return serialize_pending(saved, duplicate=True)

    # 5. 组装交易对象与扩展元数据
    extra_data = dict(data.extra or {})
    extra_data.pop('classification', None)
    extra_data.pop('transaction_type_source', None)
    if data.external_id and data.external_id.startswith('manual:'):
        extra_data['transaction_type_source'] = 'manual'
    if extra_data.get("is_initial") or extra_data.get("source") == "account_opening":
        raise HTTPException(status_code=400, detail="期初余额只能通过账户建账或对账接口创建")

    # 分类处理：优先 category_id，其次按 category_name 查找或创建
    final_category_id = None
    if data.category_id:
        from models import Category
        cat_obj = session.get(Category, data.category_id)
        if not cat_obj or (family_id and cat_obj.family_id != family_id):
            raise HTTPException(status_code=400, detail="所指定的分类不存在或属于其他家庭")
        final_category_id = cat_obj.id
    elif data.category_name:
        from models import Category
        c_name = data.category_name.strip()
        matched_cat = session.exec(
            select(Category).where(
                Category.family_id == family_id,
                or_(Category.name == c_name, Category.i18n_key == c_name),
            )
        ).first()
        if not matched_cat:
            matched_cat = Category(
                family_id=family_id,
                name=c_name,
                icon="📦",
                color="#6366f1",
            )
            session.add(matched_cat)
            session.flush()
            session.refresh(matched_cat)
        final_category_id = matched_cat.id

    from models import PendingFxTransaction
    if not account.is_active:
        raise HTTPException(409, "账户已停用")
    if data.original_amount is not None and not data.original_currency or data.original_currency and data.original_amount is None:
        raise HTTPException(422, "原币金额与币种必须同时提供")
    if data.settlement_source not in {"bank", "manual_confirmation"}:
        raise HTTPException(422, "无效结算来源")
    if data.refund_of_transaction_id:
        original = session.get(Transaction, data.refund_of_transaction_id)
        if not original or original.transaction_type != "expense":
            raise HTTPException(400, "指定原消费不存在或不是支出")
        _verify_account_write_permission(session, user_or_ctx, original.account_id, "关联原消费")
        original_account = session.get(Account, original.account_id)
        if original_account.family_id != account.family_id:
            raise HTTPException(403, "退款不能跨家庭关联")
    to_identifier = (data.extra or {}).get("to_account_id")
    if to_identifier:
        try:
            destination_id = uuid.UUID(str(to_identifier))
        except (ValueError, TypeError):
            raise HTTPException(422, "转入账户ID无效")
        destination = session.get(Account, destination_id)
        if not destination or not destination.is_active or destination.id == account.id:
            raise HTTPException(400, "转入账户无效")
        _verify_account_write_permission(session, user_or_ctx, destination.id, "转入账户")
        if destination.family_id != account.family_id or destination.currency != account.currency:
            raise HTTPException(400, "转账账户必须同家庭同记账币种")

    try:
        with session.begin_nested():
            booking = prepare_booking(session, account, data.original_amount or amount,
                data.original_currency or data.currency or account.currency, transacted_date,
                data.settlement_amount, data.settlement_currency, data.master_settlement_amount,
                data.master_settlement_currency, data.settlement_source, occurred_at=occurred_at_clean)
            tags_list = [str(t).strip() for t in (data.tags or []) if str(t).strip()]
            is_reimb = "待报销" in tags_list or bool(extra_data.get("is_reimbursable"))

            txn = Transaction(
                account_id=account.id,
                external_id=data.external_id,
                transacted_at=transacted_date,
                occurred_at=occurred_at_clean,
                **booking,
                narration=data.narration,
                category_id=final_category_id,
                category_source="manual" if final_category_id else "import",
                transaction_type=txn_type,
                status="cleared",
                is_reimbursable=is_reimb,
                reimbursement_status="pending" if is_reimb else None,
                excluded_from_stats=bool(extra_data.get("excluded_from_stats") or is_reimb),
                notes=data.notes,
                tags=tags_list,
                extra=extra_data,
            )

            # 执行自动化规则引擎清洗与自动分类 (Rules Pipeline)
            active_rules = session.exec(
                select(Rule).where(Rule.family_id == family_id, Rule.is_active == True).order_by(Rule.priority)
            ).all()
            pipeline = RulePipeline(active_rules, session=session)
            pipeline.process_transaction(txn, account_name=account.name, dry_run=False)

            # All matching follows the final rule result, not the original input type.
            txn_type = txn.transaction_type
            if txn_type != "refund":
                txn.refund_of_transaction_id = None

            amount = txn.amount

            # 6.5. 若为转账且指定了目标账户（to_account_id），先严格校验权限再原子提交
            to_acc_id_str = extra_data.get("to_account_id") if isinstance(extra_data, dict) else None
            to_account = None
            if to_acc_id_str and txn_type != "transfer":
                raise HTTPException(400, "指定转入账户的流水必须保持转账类型")
            if (txn_type == "transfer" or to_acc_id_str) and to_acc_id_str:
                try:
                    to_acc_uuid = uuid.UUID(str(to_acc_id_str))
                    to_account = session.get(Account, to_acc_uuid)
                    if not to_account or not to_account.is_active:
                        raise HTTPException(status_code=400, detail="指定的转入目标账户不存在或已停用")
                    if to_account.id == account.id:
                        raise HTTPException(status_code=400, detail="转入与转出不能为同一账户")
                    if to_account.family_id != (account.family_id or family_id):
                        raise HTTPException(status_code=400, detail="转入账户必须属于同一家庭")
                    _verify_account_write_permission(session, user_or_ctx, to_account.id, "转入资金")
                    if to_account.currency != account.currency:
                        raise HTTPException(status_code=400, detail="跨币种转账需要明确兑换金额")
                except HTTPException:
                    raise
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail="无效的目标账户 ID")

            if pending_record is not None:
                txn.id = pending_record.id
            session.add(txn)

            if to_account:
                in_name = data.narration if data.narration and data.narration not in ("转账", "内部转账") else f"收到{account.name}转入"
                in_txn = Transaction(
                    account_id=to_account.id,
                    amount=amount,
                    currency=account.currency,
                    narration=in_name,
                    transaction_type="transfer",
                    category_id=txn.category_id,
                    category_source=txn.category_source,
                    transacted_at=transacted_date,
                    occurred_at=occurred_at_clean,
                    notes=data.notes,
                    status="posted",
                    extra={"from_account_id": str(account.id), "transaction_type_source": "manual"},
                )
                session.add(in_txn)
                session.flush()

                transfer_record = Transfer(
                    family_id=account.family_id or family_id,
                    outflow_transaction_id=txn.id,
                    inflow_transaction_id=in_txn.id,
                    amount=amount,
                    status="confirmed",
                )
                session.add(transfer_record)
                session.flush()

                txn.transfer_id = transfer_record.id
                txn.transaction_type = "transfer"
                in_txn.transfer_id = transfer_record.id
                session.add(txn)
                session.add(in_txn)
                logger.info("自动创建转账对端流水并原子配对: from=%s to=%s amount=%s transfer_id=%s", account.id, to_account.id, amount, transfer_record.id)

            # 预检显式退款目标有效性及权限（防止事务提交后报错产生孤儿退款流水）
            if txn_type == "refund" and data.refund_of_transaction_id:
                cand = session.get(Transaction, data.refund_of_transaction_id)
                if not cand or cand.transaction_type != "expense":
                    raise HTTPException(status_code=400, detail="指定的原消费不存在或不是支出类型交易")
                cand_acc = session.get(Account, cand.account_id)
                if not cand_acc or cand_acc.family_id != family_id:
                    raise HTTPException(status_code=400, detail="原消费必须属于同一家庭")
                from services.stats_engine import get_user_writable_account_ids
                is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
                curr_user_obj = session.exec(select(User).where(User.username == user_or_ctx)).first() if (isinstance(user_or_ctx, str) and not is_service) else None
                writable_acc_ids = get_user_writable_account_ids(session, user_or_ctx if is_service else curr_user_obj, family_id=family_id)
                if cand_acc.id not in writable_acc_ids:
                    raise HTTPException(status_code=403, detail="无权将退款关联至未授权的私有账户消费")

            session.flush()
            session.refresh(txn)

            # 7. 智能转账自动对齐撮合 (2 天容差，跨账户，同金额，同家庭，且具备明确互逆转账语义)
            if txn_type in ("transfer", "expense", "income") and not txn.transfer_id:
                from services.stats_engine import get_user_writable_account_ids
                is_service = isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:")
                curr_user_obj = session.exec(select(User).where(User.username == user_or_ctx)).first() if (isinstance(user_or_ctx, str) and not is_service) else None
                writable_acc_ids = get_user_writable_account_ids(session, user_or_ctx if is_service else curr_user_obj, family_id=family_id)

                def _detect_transfer_flow(t: Transaction) -> Optional[str]:
                    from services.transaction_direction import transaction_direction
                    if t.transaction_type == 'expense' and (t.extra or {}).get('bank_action') == '支付':
                        return None
                    explicit = (t.extra or {}).get("direction")
                    if t.transaction_type == "transfer" and explicit in ("in", "inflow", "out", "outflow"):
                        return "in" if transaction_direction(t, session) == "inflow" else "out"
                    text = f"{t.narration or ''} {t.notes or ''}".lower()
                    has_out = any(k in text for k in ["转出", "转账给", "转给", "汇出", "转往", "提现到", "outflow", "transfer to"])
                    has_in = any(k in text for k in ["转入", "收到转账", "汇入", "转自", "inflow", "transfer from"])
                    general = any(k in text for k in ["转账", "划转", "transfer", "还款", "网上还款"])
                    if has_out and has_in:
                        return None
                    if t.transaction_type == "expense":
                        return "out" if (has_out or general) and not has_in else None
                    if t.transaction_type == "income":
                        return "in" if (has_in or general) and not has_out else None
                    if t.transaction_type == "transfer" and (has_in or has_out):
                        flow = "in" if has_in else "out"
                        account_obj = session.get(Account, t.account_id)
                        actual = "in" if transaction_direction(t, session, account_obj) == "inflow" else "out"
                        return flow if flow == actual else None
                    return None

                txn_flow = _detect_transfer_flow(txn)
                # 仅当当前交易本身显式具有转账类型或方向关键词时才触发自动撮合，避免误将普通消费/薪资收入转为转账
                should_match_transfer = (txn_type == "transfer") or (txn_flow is not None)

                if should_match_transfer:
                    cand_start = transacted_date - timedelta(days=2)
                    cand_end = transacted_date + timedelta(days=2)

                    cand_types = None
                    if txn_type == "expense":
                        cand_types = ("income", "transfer")
                    elif txn_type == "income":
                        cand_types = ("expense", "transfer")

                    cand_query = select(Transaction).join(Account, Transaction.account_id == Account.id).where(
                        Account.family_id == family_id,
                        Transaction.id != txn.id,
                        Transaction.account_id != txn.account_id,
                        Transaction.amount == amount,
                        Transaction.currency == txn.currency,
                        Transaction.transacted_at >= cand_start,
                        Transaction.transacted_at <= cand_end,
                        Transaction.transfer_id.is_(None),
                    )
                    # 严格权限收敛：候选账户必须对当前用户可写，杜绝跨私有账户篡改
                    cand_query = cand_query.where(Transaction.account_id.in_(writable_acc_ids))

                    if cand_types:
                        cand_query = cand_query.where(Transaction.transaction_type.in_(cand_types))

                    candidate_rows = session.exec(cand_query).all()

                    out_txn, in_txn = None, None
                    for candidate in candidate_rows:
                        cand_flow = _detect_transfer_flow(candidate)
                        if txn_flow == "out" and cand_flow == "in":
                            out_txn, in_txn = txn, candidate
                            break
                        if txn_flow == "in" and cand_flow == "out":
                            out_txn, in_txn = candidate, txn
                            break

                    if out_txn and in_txn:
                        # 校验是否在已驳回黑名单中
                        is_rejected = session.exec(
                            select(RejectedTransfer).where(
                                RejectedTransfer.outflow_transaction_id == out_txn.id,
                                RejectedTransfer.inflow_transaction_id == in_txn.id,
                            )
                        ).first()

                        if not is_rejected:
                            transfer_record = Transfer(
                                family_id=family_id,
                                outflow_transaction_id=out_txn.id,
                                inflow_transaction_id=in_txn.id,
                                amount=amount,
                                status="confirmed",
                            )
                            session.add(transfer_record)
                            session.flush()
                            session.refresh(transfer_record)

                            out_txn.transfer_id = transfer_record.id
                            out_txn.transaction_type = "transfer"
                            in_txn.transfer_id = transfer_record.id
                            in_txn.transaction_type = "transfer"
                            session.add(out_txn)
                            session.add(in_txn)
                            session.flush()
                            logger.info("自动撮合转账对: outflow=%s inflow=%s amount=%s", out_txn.id, in_txn.id, amount)

            # Native refund quotas and booked offsets are validated by one service.
            if txn.transaction_type == "refund":
                from services.refund_money import auto_allocate
                auto_allocate(session, user_or_ctx, txn, data.refund_of_transaction_id,
                              data.allocation_amount, data.allocation_currency, data.refund_original_amount)

            if pending_record is not None:
                pending_record.status = "posted"
                pending_record.posted_transaction_id = txn.id
                pending_record.last_error = None
                session.add(pending_record)
            return {
                "id": str(txn.id),
                "account_id": str(txn.account_id),
                "external_id": txn.external_id,
                "amount": money_text(txn.amount),
                **money_metadata(txn),
                "currency": txn.currency,
                "narration": txn.narration,
                "name": txn.narration,
                "transaction_type": txn.transaction_type,
                "transacted_at": txn.transacted_at.isoformat(),
                "occurred_at": serialize_utc_datetime(txn.occurred_at),
                "status": "created",
            }

    except PendingExchangeRate as error:
        from routes.v1_pending_fx import serialize_pending
        row = pending_record or PendingFxTransaction(account_id=account.id, family_id=account.family_id,
            requested_by_user_id=current_user.id if current_user else None,
            requested_by_service=current_user is None, external_id=data.external_id)
        row.payload = {**data.model_dump(mode="json"), "account": str(account.id)}
        row.status = "pending_fx"
        row.last_error = str(error)[:500]
        session.add(row)
        session.flush()
        return serialize_pending(row)


@router.get("")
@router.get("/")
def list_transactions(
    account_id: Optional[str] = Query(None, description="按账户ID过滤，支持逗号分隔多选"),
    account_mask: Optional[str] = Query(None, description="按卡号后4位过滤，支持逗号分隔多选"),
    institution_name: Optional[str] = Query(None, description="按金融机构名称过滤，支持逗号分隔多选"),
    category_id: Optional[str] = Query(None, description="按分类ID过滤，支持逗号分隔多选"),
    transaction_type: Optional[str] = Query(None, description="按交易类型过滤，支持逗号分隔多选"),
    category_name: Optional[str] = Query(None, description="按分类名称过滤，支持逗号分隔多选"),
    spending_net: bool = Query(False, description="分类报表明细：按原消费分类包含退款，返回展示币种净额"),
    spending_currency: Optional[CurrencyCode] = None,
    is_refund: Optional[bool] = Query(None, description="仅看退款相关交易"),
    has_refund: Optional[bool] = Query(None, description="仅看已关联退款冲抵的消费"),
    tag: Optional[str] = Query(None, description="按标签过滤，支持逗号分隔多选"),
    merchant: Optional[str] = Query(None, description="按商户名称过滤，支持逗号分隔多选"),
    merchant_group: Optional[Literal['other']] = Query(None, description="商户支出图中，除单独显示的商户以外的消费"),
    status: Optional[str] = Query(None, description="按交易状态过滤: cleared | pending，支持逗号分隔多选"),
    min_amount: Optional[Decimal] = Query(None, description="最小交易金额"),
    max_amount: Optional[Decimal] = Query(None, description="最大交易金额"),
    search: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    user: Optional[str] = Query(None, description="按所属家庭成员筛选 (username / display_name / 全部)"),
    limit: int = Query(50, ge=1, le=500),
    cursor: Optional[str] = Query(None, description="Keyset pagination cursor"),
    offset: Optional[int] = Query(None, description="Offset pagination"),
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    极速游标分页交易流水列表（支持全面多维复合筛选：卡号、金融机构、消费类型、分类、退款、标签、金额与日期）。
    """
    from services.ledger_read import LedgerRead
    read = LedgerRead(session)
    def resolve_cat(t):
        account = read.account(t.account_id)
        c = read.family_categories(account.family_id).get(t.category_id) if account and t.category_id else None
        return (c.name, c.icon or "📦") if c else ("其他", "📦")

    stmt = select(Transaction)

    current_user = None
    accessible_acc_ids = set()
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    # 核心权限隔离矩阵：任何成员仅能检索其名下或显式授权共享给其的账户交易流水
    if current_user:
        from services.stats_engine import get_user_visible_account_ids
        accessible_acc_ids = get_user_visible_account_ids(session, current_user, current_user.family_id)
        if not accessible_acc_ids:
            return {"items": [], "has_more": False, "next_cursor": None, "count": 0}
        stmt = stmt.where(Transaction.account_id.in_(list(accessible_acc_ids)))

    if isinstance(user_or_ctx, str) and user_or_ctx.startswith("service:"):
        from services.principals import service_family
        ids = session.exec(select(Account.id).where(Account.family_id == service_family(session).id)).all()
        accessible_acc_ids = set(ids)
        stmt = stmt.where(Transaction.account_id.in_(ids))

    target_u = None
    if isinstance(user, str) and user.strip() and user.strip() not in ("全部", "ALL", "all"):
        user_val = user.strip()
        target_u = session.exec(select(User).where(or_(User.username == user_val, User.display_name == user_val))).first()
        if target_u:
            u_accs = session.exec(select(Account.id).where(Account.owner_id == target_u.id)).all()
            if u_accs:
                stmt = stmt.where(Transaction.account_id.in_(u_accs))
            else:
                return {"items": [], "has_more": False, "next_cursor": None, "count": 0}

    selected_spending_accounts = None
    if isinstance(account_id, str) and account_id.strip():
        acc_id_strs = [s.strip() for s in str(account_id).split(",") if s.strip()]
        parsed_uuids = []
        for s in acc_id_strs:
            try:
                parsed_uuids.append(uuid.UUID(s))
            except ValueError:
                pass
        if parsed_uuids:
            if current_user:
                # 首先校验被查询账户当前用户是否拥有访问权限，未授权的直接拦截
                authorized_uuids = [u for u in parsed_uuids if u in accessible_acc_ids]
                if not authorized_uuids:
                    return {"items": [], "has_more": False, "next_cursor": None, "count": 0}
                expanded_uuids = set(authorized_uuids)
                # 仅对已授权的主卡穿透其名下附属卡明细，且附属卡也必须在当前用户可见范围内
                for pid in authorized_uuids:
                    child_ids = session.exec(select(Account.id).where(Account.parent_account_id == pid)).all()
                    for cid in child_ids:
                        if cid in accessible_acc_ids:
                            expanded_uuids.add(cid)
            else:
                expanded_uuids = set(parsed_uuids)
                for pid in parsed_uuids:
                    child_ids = session.exec(select(Account.id).where(Account.parent_account_id == pid)).all()
                    for cid in child_ids:
                        expanded_uuids.add(cid)

            if spending_net is True:
                selected_spending_accounts = expanded_uuids
            elif len(expanded_uuids) == 1:
                stmt = stmt.where(Transaction.account_id == list(expanded_uuids)[0])
            else:
                stmt = stmt.where(Transaction.account_id.in_(list(expanded_uuids)))
        else:
            return {"items": [], "has_more": False, "next_cursor": None, "count": 0}

    if isinstance(institution_name, str) and institution_name.strip():
        inst_names = [i.strip() for i in institution_name.split(",") if i.strip()]
        inst_conds = []
        for iname in inst_names:
            inst_conds.append(Account.institution_name.ilike(f"%{iname}%"))
            inst_conds.append(Account.name.ilike(f"%{iname}%"))
        inst_accs = session.exec(select(Account).where(or_(*inst_conds))).all() if inst_conds else []
        if inst_accs:
            stmt = stmt.where(Transaction.account_id.in_([a.id for a in inst_accs]))
        else:
            return {"items": [], "has_more": False, "next_cursor": None, "count": 0}

    if isinstance(account_mask, str) and account_mask.strip():
        cleaned_masks = [m.strip().lstrip("*") for m in account_mask.split(",") if m.strip()]
        mask_conds = []
        for m in cleaned_masks:
            mask_conds.append(Account.name.ilike(f"%{m}%"))
            mask_conds.append(Account.external_identifier.ilike(f"%{m}%"))
        mask_accs = session.exec(select(Account).where(or_(*mask_conds))).all() if mask_conds else []
        if mask_accs:
            stmt = stmt.where(Transaction.account_id.in_([a.id for a in mask_accs]))
        else:
            return {"items": [], "has_more": False, "next_cursor": None, "count": 0}

    parsed_cat_uuids = []
    if spending_net is not True and isinstance(category_id, str) and category_id.strip():
        cat_id_strs = [s.strip() for s in str(category_id).split(",") if s.strip()]
        for s in cat_id_strs:
            try:
                parsed_cat_uuids.append(uuid.UUID(s))
            except ValueError:
                pass
        if parsed_cat_uuids:
            # Refunds are classified by their originals below, including splits.
            stmt = stmt.where(or_(Transaction.category_id.in_(parsed_cat_uuids),
                                  Transaction.transaction_type == "refund"))

    if isinstance(transaction_type, str) and transaction_type.strip():
        types = [t.strip() for t in transaction_type.split(",") if t.strip()]
        if len(types) == 1:
            stmt = stmt.where(Transaction.transaction_type == types[0])
        elif len(types) > 1:
            stmt = stmt.where(Transaction.transaction_type.in_(types))

    if is_refund is True:
        stmt = stmt.where(
            or_(
                Transaction.transaction_type == "refund",
                Transaction.refund_of_transaction_id.is_not(None),
                Transaction.narration.ilike("%退款%"),
            )
        )
    if has_refund is True:
        stmt = stmt.where(Transaction.id.in_(select(RefundAllocation.original_transaction_id)))
    if isinstance(min_amount, (Decimal, int, float)):
        stmt = stmt.where(func.abs(Transaction.amount) >= min_amount)
    if isinstance(max_amount, (Decimal, int, float)):
        stmt = stmt.where(func.abs(Transaction.amount) <= max_amount)
    if isinstance(start_date, (date, datetime)):
        stmt = stmt.where(Transaction.transacted_at >= start_date)
    if isinstance(end_date, (date, datetime)):
        stmt = stmt.where(Transaction.transacted_at <= end_date)
    if isinstance(search, str) and search.strip():
        kw = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Transaction.narration.ilike(kw),
                Transaction.notes.ilike(kw),
            )
        )
    if isinstance(merchant, str) and merchant.strip():
        merchants = [m.strip() for m in merchant.split(",") if m.strip()]
        m_conds = []
        for m in merchants:
            m_kw = f"%{m}%"
            m_conds.append(Transaction.narration.ilike(m_kw))
        if m_conds:
            stmt = stmt.where(or_(*m_conds))

    if isinstance(status, str) and status.strip():
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            stmt = stmt.where(Transaction.status == statuses[0])
        elif len(statuses) > 1:
            stmt = stmt.where(Transaction.status.in_(statuses))

    other_merchant_names = None
    if merchant_group == 'other':
        from services.dashboard_scope import dashboard_scope
        from services.report_currency import ReportCurrency, persist_fx_cache
        from services.merchant_spending import ranked_merchants, MERCHANT_TILE_LIMIT
        actor, _, _, report_accounts, _, _ = dashboard_scope(session, user_or_ctx, user)
        report_ids = {a.id for a in report_accounts}
        group_stmt = select(Transaction).where(
            Transaction.account_id.in_(report_ids) if report_ids else False,
            Transaction.excluded_from_stats == False,
            Transaction.transaction_type == 'expense',
        )
        if isinstance(start_date, date):
            group_stmt = group_stmt.where(Transaction.transacted_at >= start_date)
        if isinstance(end_date, date):
            group_stmt = group_stmt.where(Transaction.transacted_at <= end_date)
        money = ReportCurrency(session, actor, cache_independently=True)
        money.account_ids = report_ids
        ranking, _ = ranked_merchants(money.transactions(session.exec(group_stmt).all()))
        other_merchant_names = {name for name, _ in ranking[MERCHANT_TILE_LIMIT:]}
        persist_fx_cache(session)
        stmt = stmt.where(
            Transaction.account_id.in_(report_ids) if report_ids else False,
            Transaction.excluded_from_stats == False,
            Transaction.transaction_type == 'expense',
        )

    from services.principals import resolve_family_id
    family_id = current_user.family_id if current_user else resolve_family_id(session, user_or_ctx)
    report_ids, category_map = set(), {}
    if spending_net is True:
        from services.stats_engine import get_user_report_account_ids
        if current_user:
            report_ids = get_user_report_account_ids(session, current_user, current_user.family_id,
                                                    visible_ids=accessible_acc_ids)
        else:
            from services.principals import service_family
            report_ids = set(session.exec(select(Account.id).where(
                Account.family_id == service_family(session).id, Account.is_active == True,
                Account.exclude_from_reports == False)).all())
        if target_u:
            report_ids &= set(session.exec(select(Account.id).where(Account.owner_id == target_u.id)).all())
        # These rows cannot contribute to spending or refund offsets. Filter
        # them in SQL before ORM loading, while retaining refunds on other
        # cards that may offset an original on the selected spending account.
        stmt = stmt.where(Transaction.account_id.in_(report_ids) if report_ids else False,
                          Transaction.transaction_type.in_(['expense', 'refund']),
                          Transaction.excluded_from_stats == False)
        if selected_spending_accounts is not None:
            stmt = stmt.where(or_(Transaction.transaction_type == 'refund',
                                  Transaction.account_id.in_(selected_spending_accounts)))
        category_map = read.family_categories(family_id)

    # Apply the same newest-first order before pagination and in daily groups.
    stmt = stmt.order_by(
        desc(Transaction.transacted_at),
        desc(func.coalesce(Transaction.occurred_at, Transaction.created_at)),
        desc(Transaction.created_at),
        desc(Transaction.id),
    )
    memory_filter = (spending_net is True or other_merchant_names is not None or bool(parsed_cat_uuids)
        or (isinstance(category_name, str) and bool(category_name.strip()))
        or (isinstance(tag, str) and bool(tag.strip())))
    all_matched = session.exec(stmt).all() if memory_filter else []
    if memory_filter:
        read.prepare(all_matched)
    if other_merchant_names is not None:
        all_matched = [t for t in all_matched if (t.narration or '其他') in other_merchant_names]
    from services.tags import tag_resolver
    resolve_tags = tag_resolver(session, family_id)

    refund_categories = {}
    def refund_categories_for(t):
        if t.id not in refund_categories:
            from services.refund_money import refund_category_details
            refund_categories[t.id] = refund_category_details(session, t, accessible_acc_ids,
                allocations=read.allocations.get(t.id, []), read=read)
        return refund_categories[t.id]

    def effective_categories(t):
        if t.transaction_type == "refund":
            info = refund_categories_for(t)
            return info['linked_categories'] + ([info['unallocated_category']] if info['category_editable'] else [])
        name, icon = resolve_cat(t)
        return [{"id": str(t.category_id) if t.category_id else None, "name": name, "icon": icon}]

    spending_amounts, spending_summary, spending_categories = {}, None, {}
    if spending_net is True:
        from services.stats_engine import spending_category_portions
        from services.report_currency import ReportCurrency
        converter = ReportCurrency(session, current_user, currency=spending_currency, cache_independently=True)
        converter.account_ids = report_ids
        converter.read = read
        converter.prepare(t for t in all_matched if t.account_id in report_ids
            and not t.excluded_from_stats and t.transaction_type in ('expense', 'refund')
            and (t.transaction_type == 'refund' or selected_spending_accounts is None
                 or t.account_id in selected_spending_accounts))
        cat_names = set(c.strip() for c in category_name.split(',')) if isinstance(category_name, str) and category_name else None
        cat_ids = set(c.strip() for c in category_id.split(',')) if isinstance(category_id, str) and category_id else None
        selected = []
        for t in all_matched:
            if t.account_id not in report_ids:
                continue
            portions = [(cat, value) for cat, value in spending_category_portions(
                session, t, category_map, report_ids, converter, selected_spending_accounts)
                if (cat_names is None or cat['name'] in cat_names) and (cat_ids is None or cat['id'] in cat_ids)]
            if not portions:
                continue
            selected.append(t)
            spending_amounts[t.id] = sum((value for _, value in portions), Decimal(0))
            spending_categories[t.id] = [cat['name'] for cat, _ in portions]
        all_matched = selected
        spending_summary = {"currency": converter.currency, "currency_symbol": converter.symbol}

    # Ordinary filters also recognize inherited categories of linked refunds.
    elif isinstance(category_name, str) and category_name.strip():
        cat_names = set(c.strip() for c in category_name.split(",") if c.strip())
        all_matched = [t for t in all_matched if any(c['name'] in cat_names for c in effective_categories(t))]

    if spending_net is not True and parsed_cat_uuids:
        category_ids = {str(c) for c in parsed_cat_uuids}
        all_matched = [t for t in all_matched if any(c['id'] in category_ids for c in effective_categories(t))]

    # If tag provided, filter in memory (支持逗号分隔多选)
    if isinstance(tag, str) and tag.strip():
        cleaned_tags = [tg.strip().lower() for tg in tag.split(",") if tg.strip()]
        all_matched = [
            t for t in all_matched
            if any(any(ct in str(x).lower() for ct in cleaned_tags) for x in resolve_tags(t.tags))
            or (t.notes and any(ct in t.notes.lower() for ct in cleaned_tags))
        ]

    effective_limit = limit if isinstance(limit, int) else 50
    if spending_summary is not None:
        from services.booking_money import money
        expense = sum((spending_amounts[t.id] for t in all_matched if t.transaction_type == 'expense'), Decimal(0))
        refunds = -sum((spending_amounts[t.id] for t in all_matched if t.transaction_type == 'refund'), Decimal(0))
        spending_summary.update(expense=float(money(expense)), refunds=float(money(refunds)),
                                net=float((expense - refunds).quantize(Decimal('0.01'))))
    if memory_filter:
        total_count = len(all_matched)
        start_idx = 0
        if cursor and str(cursor).strip():
            cursor_str = str(cursor).strip()
            for i, t in enumerate(all_matched):
                if str(t.id) == cursor_str:
                    start_idx = i + 1
                    break
        elif offset and isinstance(offset, int) and offset > 0:
            start_idx = min(offset, len(all_matched))
        sliced = all_matched[start_idx:]
        has_more = len(sliced) > effective_limit
        items = sliced[:effective_limit]
    else:
        from services.transaction_pagination import transaction_page
        items, has_more, total_count = transaction_page(session, stmt, effective_limit, cursor, offset)
        read.prepare(items)

    import re

    # 预加载 transfer 交易的对端信息（用于列表显示 from/to）
    from models import Transfer as TransferModel
    transfer_ids = [t.transfer_id for t in items if t.transaction_type == "transfer" and t.transfer_id]
    transfers_map: dict = {}
    if transfer_ids:
        trs = session.exec(select(TransferModel).where(TransferModel.id.in_(transfer_ids))).all()
        transfers_map = {tr.id: tr for tr in trs}
    # 收集需要查的对端 transaction id
    peer_txn_ids = []
    for t in items:
        if t.transaction_type == "transfer" and t.transfer_id and t.transfer_id in transfers_map:
            tr = transfers_map[t.transfer_id]
            peer_id = tr.inflow_transaction_id if t.id == tr.outflow_transaction_id else tr.outflow_transaction_id
            if peer_id:
                peer_txn_ids.append(peer_id)
    peer_txns_map: dict = {}
    if peer_txn_ids:
        peer_txns = session.exec(select(Transaction).where(Transaction.id.in_(peer_txn_ids))).all()
        peer_txns_map = {pt.id: pt for pt in peer_txns}

    read.load_accounts(row.account_id for row in peer_txns_map.values())
    accounts_map = read.accounts
    owner_ids = {acc.owner_id for acc in accounts_map.values() if acc.owner_id and acc.id in accessible_acc_ids}
    users_map = {u.id: (u.display_name or u.username) for u in session.exec(select(User).where(User.id.in_(owner_ids))).all()} if owner_ids else {}

    output = []
    for t in items:
        acc = accounts_map.get(t.account_id)
        acc_name = acc.name if acc else "招商银行账户"
        acc_is_owner = bool(current_user and acc and acc.owner_id == current_user.id)
        acc_owner = users_map.get(acc.owner_id) if (acc and acc.owner_id) else None
        m = re.search(r"\(([0-9Xx]{4})\)", acc_name)
        mask = m.group(1) if m else (acc_name[-4:] if len(acc_name) >= 4 else "0000")
        cname, cicon = resolve_cat(t)
        displayed_category_id = str(t.category_id) if t.category_id else None
        refund_category_info = refund_categories_for(t) if t.transaction_type == "refund" else None
        if refund_category_info and not refund_category_info['category_editable']:
            linked = refund_category_info['linked_categories']
            cname = " / ".join(c['name'] for c in linked) or "随原消费分类"
            cicon = linked[0]['icon'] if len(linked) == 1 else "🗂️"
            displayed_category_id = linked[0]['id'] if len(linked) == 1 else None

        occurred_at_val = None
        if t.occurred_at:
            occurred_at_val = serialize_utc_datetime(t.occurred_at)
        elif t.created_at:
            occurred_at_val = serialize_utc_datetime(t.created_at)
        elif t.transacted_at:
            occurred_at_val = f"{t.transacted_at.isoformat()}T00:00:00Z"

        # 计算转账方向和对端账户名及归属
        transfer_is_outflow = None
        transfer_peer_account = None
        transfer_peer_owner_name = None
        transfer_peer_is_owner = None
        if t.transaction_type == "transfer" and t.transfer_id and t.transfer_id in transfers_map:
            tr = transfers_map[t.transfer_id]
            transfer_is_outflow = (t.id == tr.outflow_transaction_id)
            peer_id = tr.inflow_transaction_id if transfer_is_outflow else tr.outflow_transaction_id
            if peer_id and peer_id in peer_txns_map:
                peer_txn = peer_txns_map[peer_id]
                peer_acc = accounts_map.get(peer_txn.account_id)
                if peer_acc:
                    is_peer_visible = not current_user or (peer_acc.id in accessible_acc_ids)
                    transfer_peer_account = peer_acc.name if is_peer_visible else "私有账户"
                    transfer_peer_owner_name = (users_map.get(peer_acc.owner_id) if peer_acc.owner_id else None) if is_peer_visible else "私有成员"
                    transfer_peer_is_owner = bool(current_user and peer_acc.owner_id == current_user.id) if is_peer_visible else False
                else:
                    transfer_peer_account = "外部账户"

        output.append({
            "id": str(t.id),
            "account_id": str(t.account_id),
            "account_name": acc_name,
            "account_mask": mask,
            "account_owner": acc_owner or ("本人" if acc_is_owner else "我的"),
            "account_owner_name": acc_owner,
            "account_is_owner": acc_is_owner,
            "account_owner_id": str(acc.owner_id) if acc and acc.owner_id else None,
            "institution_name": acc.institution_name if acc else None,
            "external_id": t.external_id,
            "transacted_at": t.transacted_at.isoformat(),
            "occurred_at": occurred_at_val,
            "amount": money_text(t.amount),
            **({"spending_amount": money_text(spending_amounts[t.id]),
                "spending_currency": spending_summary['currency'],
                "spending_categories": spending_categories[t.id]} if spending_summary else {}),
            **money_metadata(t),
            "currency": t.currency,
            "narration": t.narration,
            "name": t.narration,
            "category_id": displayed_category_id,
            "category_name": cname,
            "category_icon": cicon,
            "refund_category_info": refund_category_info,
            "transaction_type": t.transaction_type,
            "status": t.status,
            "transfer_id": str(t.transfer_id) if t.transfer_id else None,
            "refund_of_transaction_id": str(t.refund_of_transaction_id) if t.refund_of_transaction_id else None,
            "is_split": bool(t.is_split),
            "is_reimbursable": bool(t.is_reimbursable or (t.extra and t.extra.get("reimbursement_type"))),
            "reimbursement_status": t.reimbursement_status or (("待还款" if (t.extra and t.extra.get("reimbursement_type") == "personal_advance") else "审批中") if (t.extra and t.extra.get("reimbursement_type")) else None),
            "excluded_from_stats": bool(t.excluded_from_stats),
            "extra": t.extra or {},
            "notes": t.notes,
            "tags": resolve_tags(t.tags),
            "transfer_is_outflow": transfer_is_outflow,
            "transfer_peer_account": transfer_peer_account,
            "transfer_peer_owner_name": transfer_peer_owner_name,
            "transfer_peer_is_owner": transfer_peer_is_owner,
        })

    next_cursor = output[-1]["id"] if has_more and output else None

    return {
        "items": output,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "count": len(output),
        "total_count": total_count,
        "spending_summary": spending_summary,
    }


@router.get("/filter-options")
def get_filter_options(
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    获取交易流水全维筛选选项元数据：卡号/账户列表、金融机构、消费类型、分类与标签。
    严格执行多租户与账户权限隔离，仅返回当前用户有权访问的本家庭资产元数据。
    """
    curr_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        curr_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    if not curr_user or not curr_user.family_id:
        return {
            "accounts": [],
            "institutions": [],
            "merchants": [],
            "categories": [],
            "tags": [],
            "statuses": [{"value": "cleared", "label": "已清算"}, {"value": "pending", "label": "待入账"}],
            "transaction_types": [{"value": "expense", "label": "支出"}, {"value": "income", "label": "收入"}, {"value": "transfer", "label": "内部转账"}, {"value": "refund", "label": "退款冲抵"}],
        }

    family_id = curr_user.family_id
    user_map = {u.id: (u.display_name or u.username) for u in session.exec(select(User).where(User.family_id == family_id)).all()}

    # 仅获取当前家庭下用户有权查看的活跃账户（遵循严格共享授权，杜绝越权与属性异常）
    from services.stats_engine import get_user_visible_account_ids
    visible_acc_ids = get_user_visible_account_ids(session, curr_user, family_id=family_id)
    if visible_acc_ids:
        accounts = session.exec(
            select(Account).where(Account.id.in_(visible_acc_ids))
        ).all()
    else:
        accounts = []

    acc_ids = [a.id for a in accounts]
    accounts_data = []
    institutions_set = set()
    import re
    for a in accounts:
        m = re.search(r"(\d{4})", a.name or "")
        mask = m.group(1) if m else (a.name[-4:] if len(a.name) >= 4 else "0000")
        inst = a.institution_name or ""
        if inst:
            institutions_set.add(inst)

        is_mine = bool(curr_user and a.owner_id == curr_user.id)
        if is_mine:
            has_shares = session.exec(
                select(AccountShare).where(
                    AccountShare.account_id == a.id,
                    AccountShare.user_id != curr_user.id
                )
            ).first() is not None
            badge = "我的 · 已共享" if has_shares else "我的"
        else:
            owner = user_map.get(a.owner_id, "家庭成员")
            badge = f"{owner}共享给我"

        accounts_data.append({
            "id": str(a.id),
            "name": a.name,
            "mask": mask,
            "institution_name": inst,
            "account_type": a.account_type,
            "owner": user_map.get(a.owner_id, "家庭成员"),
            "owner_id": str(a.owner_id) if a.owner_id else None,
            "is_mine": is_mine,
            "badge": badge,
        })

    # 提取标签（严格限定在授权账户范围内）
    from services.tags import tag_resolver
    resolve_tags = tag_resolver(session, family_id)
    tags_set = set()
    merchants_set = set()
    if acc_ids:
        all_txns_tags = session.exec(
            select(Transaction.tags).where(Transaction.account_id.in_(acc_ids))
        ).all()
        for tag_list in all_txns_tags:
            if tag_list and isinstance(tag_list, list):
                for tg in resolve_tags(tag_list):
                    if tg and isinstance(tg, str):
                        tags_set.add(tg.strip())

        # 提取商户/摘要列表（严格限定在授权账户范围内）
        txns_merchants = session.exec(
            select(Transaction.narration).where(Transaction.account_id.in_(acc_ids))
        ).all()
        for tname in txns_merchants:
            n = (tname or "").strip()
            if n and len(n) > 1:
                merchants_set.add(n)

    # 分类元数据（严格限定在当前家庭范围内）
    db_cats = session.exec(select(Category).where(Category.family_id == family_id)).all()
    if db_cats:
        categories = [
            {"id": str(c.id), "name": c.name, "icon": c.icon or "📦", "color": c.color or "#6366f1"}
            for c in db_cats
        ]
    else:
        categories = [
            {"name": "餐饮美食", "icon": "🍴", "color": "#8b5cf6"},
            {"name": "超市便利", "icon": "🛒", "color": "#10b981"},
            {"name": "生活缴费", "icon": "⚡", "color": "#ef4444"},
            {"name": "交通出行", "icon": "🚗", "color": "#06b6d4"},
            {"name": "购物消费", "icon": "🛍️", "color": "#eab308"},
            {"name": "个人/转账", "icon": "👤", "color": "#0ea5e9"},
            {"name": "其他", "icon": "🍪", "color": "#f97316"},
        ]

    return {
        "accounts": accounts_data,
        "institutions": sorted(list(institutions_set)),
        "merchants": sorted(list(merchants_set)),
        "categories": categories,
        "tags": sorted(list(tags_set)),
        "statuses": [
            {"value": "cleared", "label": "已清算"},
            {"value": "pending", "label": "待入账"},
        ],
        "transaction_types": [
            {"value": "expense", "label": "支出"},
            {"value": "income", "label": "收入"},
            {"value": "transfer", "label": "内部转账"},
            {"value": "refund", "label": "退款冲抵"},
        ],
    }


class SplitItem(BaseModel):
    category_id: Optional[Union[uuid.UUID, str]] = None
    amount: Decimal = Field(..., gt=0, max_digits=19, decimal_places=4, description="拆分子项金额必须大于0")
    notes: Optional[str] = None


class SplitPayload(BaseModel):
    splits: List[SplitItem]


@router.post("/{transaction_id}/split")
def split_transaction(
    transaction_id: uuid.UUID,
    payload: SplitPayload,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """交易拆分（Split）。将一笔交易拆分为多个分类子项，校验总金额一致性。"""
    lock_mutation(session)
    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="交易不存在")

    _verify_account_write_permission(session, user_or_ctx, txn.account_id, "拆分交易")
    from services.schedules import guard_transaction
    guard_transaction(txn)

    from services.refund_money import guard_refund_category_edit
    guard_refund_category_edit(session, txn)

    if txn.transaction_type not in {"expense", "refund"}:
        raise HTTPException(400, "只有支出和退款可以拆分分类")

    if not payload.splits or len(payload.splits) < 2:
        raise HTTPException(status_code=400, detail="拆分必须包含至少两个子项")

    # 校验总金额（绝对值）
    total_splits = sum(s.amount for s in payload.splits)
    if total_splits != abs(txn.amount):
        raise HTTPException(
            status_code=400,
            detail=f"拆分子项金额总和 ({total_splits}) 必须等于交易原始金额 ({abs(txn.amount)})",
        )

    # 清除旧拆分
    existing = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)
    ).all()
    for e in existing:
        session.delete(e)

    acc = session.get(Account, txn.account_id)
    family_id = acc.family_id if acc else None

    # 写入新拆分
    for s in payload.splits:
        resolved_cat_id = None
        if s.category_id:
            try:
                c_uuid = uuid.UUID(str(s.category_id))
                cat_match = session.get(Category, c_uuid)
                if cat_match:
                    if family_id and cat_match.family_id != family_id:
                        raise HTTPException(status_code=400, detail="拆分项分类不存在或属于其他家庭")
                    resolved_cat_id = cat_match.id
                else:
                    raise HTTPException(status_code=400, detail="拆分项分类不存在")
            except (ValueError, TypeError):
                # 尝试通过名称查找真实 Category
                c_str = str(s.category_id).strip()
                cat_match = session.exec(
                    select(Category).where(
                        Category.family_id == family_id,
                        or_(Category.name == c_str, Category.i18n_key == c_str),
                    )
                ).first()
                if cat_match:
                    resolved_cat_id = cat_match.id

        split_entry = TransactionSplit(
            transaction_id=txn.id,
            category_id=resolved_cat_id,
            amount=s.amount,
            notes=s.notes,
        )
        session.add(split_entry)

    txn.is_split = True
    txn.category_source = "manual"
    session.add(txn)
    session.commit()
    session.refresh(txn)

    return {
        "transaction_id": str(txn.id),
        "is_split": True,
        "splits_count": len(payload.splits),
    }


@router.delete("/{transaction_id}/split")
def clear_transaction_splits(transaction_id: uuid.UUID,
                             session: Session = Depends(get_session),
                             user_or_ctx: Any = Depends(get_current_user_or_token)):
    lock_mutation(session)
    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(404, "交易不存在")
    _verify_account_write_permission(session, user_or_ctx, txn.account_id, "解除拆分")
    from services.schedules import guard_transaction
    from services.refund_money import guard_refund_category_edit
    guard_transaction(txn)
    guard_refund_category_edit(session, txn)
    for row in session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)).all():
        session.delete(row)
    txn.is_split = False
    txn.category_source = "manual"
    session.add(txn)
    session.commit()
    return {"transaction_id": str(txn.id), "is_split": False}


@router.get("/{transaction_id}/splits")
def get_transaction_splits(
    transaction_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取单笔交易的所有拆分明细。"""
    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="交易不存在")
    _verify_account_read_permission(session, user_or_ctx, txn.account_id, "查看交易拆分")

    splits = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id)
    ).all()

    return [
        {
            "id": str(s.id),
            "transaction_id": str(s.transaction_id),
            "category_id": str(s.category_id) if s.category_id else None,
            "amount": money_text(s.amount),
            "notes": s.notes,
            "created_at": s.created_at.isoformat(),
        }
        for s in splits
    ]


@router.get("/{transaction_id}")
def get_transaction_detail(
    transaction_id: uuid.UUID,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """获取单笔交易的完整详情，包含转账对端详情、退款冲抵绑定及拆分明细。"""
    from models import Category, Transfer, RefundAllocation

    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="交易不存在")

    account = session.get(Account, txn.account_id)
    _verify_account_read_permission(session, user_or_ctx, txn.account_id, "查看交易详情")

    current_user = None
    if isinstance(user_or_ctx, str) and not user_or_ctx.startswith("service:"):
        current_user = session.exec(select(User).where(User.username == user_or_ctx)).first()

    from services.tags import tag_resolver
    resolve_tags = tag_resolver(session, account.family_id)
    this_owner = session.get(User, account.owner_id) if account and account.owner_id else None
    this_owner_name = (this_owner.display_name or this_owner.username) if this_owner else None
    this_is_owner = bool(current_user and account and account.owner_id == current_user.id)

    from services.stats_engine import get_user_visible_account_ids
    visible_actor = current_user or (user_or_ctx if isinstance(user_or_ctx, str) and user_or_ctx.startswith('service:') else None)
    accessible_acc_ids = set(get_user_visible_account_ids(session, visible_actor, family_id=account.family_id if account else None))

    category = session.get(Category, txn.category_id) if txn.category_id else None
    cat_name = category.name if category else "其他"
    cat_icon = category.icon if category else "📦"

    # 转账对端信息
    paired_transfer = None
    if txn.transfer_id:
        tr = session.get(Transfer, txn.transfer_id)
        if tr:
            other_id = tr.inflow_transaction_id if txn.id == tr.outflow_transaction_id else tr.outflow_transaction_id
            other_txn = session.get(Transaction, other_id)
            if other_txn:
                other_acc = session.get(Account, other_txn.account_id)
                other_owner = session.get(User, other_acc.owner_id) if other_acc and other_acc.owner_id else None
                other_owner_name = (other_owner.display_name or other_owner.username) if other_owner else None
                other_is_owner = bool(current_user and other_acc and other_acc.owner_id == current_user.id)
                other_occurred_at = None
                if other_txn.occurred_at:
                    other_occurred_at = serialize_utc_datetime(other_txn.occurred_at)
                elif other_txn.created_at:
                    other_occurred_at = serialize_utc_datetime(other_txn.created_at)
                else:
                    other_occurred_at = f"{other_txn.transacted_at.isoformat()}T00:00:00Z"

                is_other_visible = not current_user or (other_acc and other_acc.id in accessible_acc_ids)
                paired_transfer = {
                    "transfer_id": str(tr.id),
                    "status": tr.status,
                    "is_outflow": txn.id == tr.outflow_transaction_id,
                    "counterpart": {
                        "id": str(other_txn.id) if is_other_visible else None,
                        "narration": other_txn.narration if is_other_visible else "[私有转账]",
                        "name": other_txn.narration if is_other_visible else "[私有转账]",
                        "amount": str(other_txn.amount.quantize(Decimal("0.01"))) if is_other_visible else None,
                        "currency": other_txn.currency if is_other_visible else None,
                        "account_id": (str(other_acc.id) if other_acc else None) if is_other_visible else None,
                        "account_name": (other_acc.name if other_acc else "外部账户") if is_other_visible else "私有账户",
                        "owner_name": other_owner_name if is_other_visible else "私有成员",
                        "owner_id": (str(other_acc.owner_id) if other_acc and other_acc.owner_id else None) if is_other_visible else None,
                        "is_owner": other_is_owner if is_other_visible else False,
                        "transacted_at": other_txn.transacted_at.isoformat() if is_other_visible else None,
                        "occurred_at": other_occurred_at if is_other_visible else None,
                    }
                }

    # 退款关联详情
    refund_info = None
    if txn.transaction_type == "refund":
        orig_txn = session.get(Transaction, txn.refund_of_transaction_id) if txn.refund_of_transaction_id else None
        orig_acc = session.get(Account, orig_txn.account_id) if orig_txn else None
        allocs = session.exec(
            select(RefundAllocation).where(RefundAllocation.refund_transaction_id == txn.id)
        ).all()
        orig_occurred_at = None
        if orig_txn:
            if orig_txn.occurred_at:
                orig_occurred_at = serialize_utc_datetime(orig_txn.occurred_at)
            elif orig_txn.created_at:
                orig_occurred_at = serialize_utc_datetime(orig_txn.created_at)
            elif orig_txn.transacted_at:
                orig_occurred_at = f"{orig_txn.transacted_at.isoformat()}T00:00:00Z"

        is_orig_visible = not current_user or (orig_acc and orig_acc.id in accessible_acc_ids)
        refund_info = {
            "is_linked": bool(allocs),
            "needs_allocation_review": bool(orig_txn and not allocs) or any(
                a.original_book_amount is None and (not txn.original_amount or not orig_txn or not orig_txn.original_amount)
                for a in allocs),
            "original_transaction": {
                "id": str(orig_txn.id) if is_orig_visible else None,
                "narration": orig_txn.narration if is_orig_visible else "[私有消费]",
                "name": orig_txn.narration if is_orig_visible else "[私有消费]",
                "amount": money_text(orig_txn.amount) if is_orig_visible else None,
                "currency": orig_txn.currency if is_orig_visible else None,
                "account_name": (orig_acc.name if orig_acc else "原账户") if is_orig_visible else "私有账户",
                "transacted_at": orig_txn.transacted_at.isoformat() if is_orig_visible else None,
                "occurred_at": orig_occurred_at if is_orig_visible else None,
            } if orig_txn else None,
            "allocated_amount": str(sum((a.refund_original_amount or a.allocated_amount for a in allocs), Decimal("0"))),
            "currency": txn.original_currency,
            "original_total": str(txn.original_amount) if txn.original_amount is not None else None,
            "allocations": [],
        }
    elif txn.transaction_type == "expense":
        allocs = session.exec(
            select(RefundAllocation).where(RefundAllocation.original_transaction_id == txn.id)
        ).all()
        if allocs:
            refund_txns = []
            for a in allocs:
                r_txn = session.get(Transaction, a.refund_transaction_id)
                if r_txn:
                    r_acc = session.get(Account, r_txn.account_id)
                    is_r_visible = not current_user or (r_acc and r_acc.id in accessible_acc_ids)
                    r_occurred_at = None
                    if r_txn.occurred_at:
                        r_occurred_at = serialize_utc_datetime(r_txn.occurred_at)
                    elif r_txn.created_at:
                        r_occurred_at = serialize_utc_datetime(r_txn.created_at)
                    elif r_txn.transacted_at:
                        r_occurred_at = f"{r_txn.transacted_at.isoformat()}T00:00:00Z"

                    refund_txns.append({
                        "id": str(r_txn.id) if is_r_visible else None,
                        "narration": r_txn.narration if is_r_visible else "[私有退款]",
                        "name": r_txn.narration if is_r_visible else "[私有退款]",
                        "amount": str(r_txn.amount.quantize(Decimal("0.01"))) if is_r_visible else None,
                        "allocated_amount": str(a.allocated_amount.quantize(Decimal("0.01"))),
                        "transacted_at": r_txn.transacted_at.isoformat() if is_r_visible else None,
                        "occurred_at": r_occurred_at if is_r_visible else None,
                    })
            refund_info = {
                "has_refunds": True,
                "total_refunded": str(sum((a.allocated_amount for a in allocs), Decimal("0")).quantize(Decimal("0.01"))),
                "refunds": refund_txns,
            }

    displayed_category_id = str(txn.category_id) if txn.category_id else None
    if refund_info:
        from services.refund_money import remaining_native
        if txn.original_amount is not None:
            remaining = remaining_native(session, txn, refund=txn.transaction_type == "refund")
            refund_info["remaining_amount"] = money_text(remaining)
            refund_info["is_fully_allocated"] = remaining == 0
        else:
            refund_info["remaining_amount"] = None
            refund_info["is_fully_allocated"] = False
        from services.refund_money import allocation_metadata
        refund_info["currency"] = txn.original_currency
        refund_info["original_total"] = str(txn.original_amount) if txn.original_amount is not None else None
        refund_info["allocations"] = []
        for allocation in allocs:
            other_id = allocation.original_transaction_id if txn.transaction_type == "refund" else allocation.refund_transaction_id
            other = session.get(Transaction, other_id)
            if other and (not current_user or other.account_id in accessible_acc_ids):
                other_acc = session.get(Account, other.account_id)
                refund_info["allocations"].append({"other_transaction_id": str(other_id),
                    "narration": other.narration, "account_name": other_acc.name if other_acc else None,
                    "transacted_at": other.transacted_at.isoformat(),
                    "occurred_at": serialize_utc_datetime(other.occurred_at or other.created_at),
                    **allocation_metadata(allocation)})
        if txn.transaction_type == "refund":
            from services.refund_money import refund_category_details
            refund_info.update(refund_category_details(session, txn, accessible_acc_ids, allocs))
            if not refund_info['category_editable']:
                linked = refund_info['linked_categories']
                cat_name = " / ".join(c['name'] for c in linked) or "随原消费分类"
                cat_icon = linked[0]['icon'] if len(linked) == 1 else "🗂️"
                displayed_category_id = linked[0]['id'] if len(linked) == 1 else None

    # 拆分项
    splits = session.exec(
        select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)
    ).all()

    occurred_at_val = None
    if txn.occurred_at:
        occurred_at_val = serialize_utc_datetime(txn.occurred_at)
    elif txn.created_at:
        occurred_at_val = serialize_utc_datetime(txn.created_at)
    elif txn.transacted_at:
        occurred_at_val = f"{txn.transacted_at.isoformat()}T00:00:00Z"

    created_at_val = serialize_utc_datetime(txn.created_at) if txn.created_at else None

    scheduled_payment = None
    if (txn.extra or {}).get('scheduled_occurrence_id'):
        from models import ScheduledOccurrence, ScheduledPlan
        try:
            occurrence_id = uuid.UUID(txn.extra['scheduled_occurrence_id'])
        except (ValueError, TypeError):
            occurrence_id = None
        row = session.get(ScheduledOccurrence, occurrence_id) if occurrence_id else None
        plan = session.get(ScheduledPlan, row.plan_id) if row else None
        if plan and plan.family_id == account.family_id and str(txn.id) in row.transaction_ids + ([str(row.linked_transaction_id)] if row.linked_transaction_id else []):
            from services.schedules import booking_plan
            plan = booking_plan(plan, row)
            try:
                for related_id in [plan.account_id, plan.destination_id]:
                    _verify_account_read_permission(session, user_or_ctx, related_id, '查看计划')
                scheduled_payment = {'plan_id': str(plan.id), 'name': plan.name, 'number': row.number,
                                     'currency': plan.currency, 'kind': plan.kind, **row.snapshot}
            except HTTPException:
                pass

    from services.transaction_direction import transaction_direction
    from services.display_money import transaction_display_money
    display_money = transaction_display_money(session, txn, current_user, splits)
    from services.transaction_deletion import deletion_info
    return {
        "id": str(txn.id),
        "external_id": txn.external_id,
        "account_id": str(txn.account_id),
        "account_name": account.name if account else "招商银行账户",
        "account_owner_name": this_owner_name,
        "account_owner_id": str(account.owner_id) if account and account.owner_id else None,
        "account_is_owner": this_is_owner,
        "transacted_at": txn.transacted_at.isoformat(),
        "occurred_at": occurred_at_val,
        "created_at": created_at_val,
        "amount": money_text(txn.amount),
        **money_metadata(txn),
        **display_money,
        "currency": txn.currency,
        "narration": txn.narration,
        "name": txn.narration,
        "category_id": displayed_category_id,
        "category_name": cat_name,
        "category_icon": cat_icon,
        "transaction_type": txn.transaction_type,
        "funds_direction": transaction_direction(txn, session, account),
        "status": txn.status,
        "is_split": bool(txn.is_split),
        "is_reimbursable": bool(txn.is_reimbursable or (txn.extra and txn.extra.get("reimbursement_type"))),
        "reimbursement_status": txn.reimbursement_status or (("待还款" if (txn.extra and txn.extra.get("reimbursement_type") == "personal_advance") else "审批中") if (txn.extra and txn.extra.get("reimbursement_type")) else None),
        "reimbursement_type": (txn.extra.get("reimbursement_type")) if txn.extra else None,
        "counterparty": (
            txn.extra.get("counterparty", {}).get("name")
            if isinstance(txn.extra.get("counterparty"), dict)
            else txn.extra.get("counterparty")
        ) if txn.extra else None,
        "excluded_from_stats": bool(txn.excluded_from_stats),
        "extra": txn.extra or {},
        "notes": txn.notes,
        "tags": resolve_tags(txn.tags),
        "scheduled_payment": scheduled_payment,
        "paired_transfer": paired_transfer,
        "deletion_info": deletion_info(session, user_or_ctx, txn, _verify_account_write_permission),
        "refund_info": refund_info,
    }


class ReimbursementUpdateRequest(BaseModel):
    is_reimbursable: Optional[bool] = None
    reimbursement_status: Optional[str] = None
    excluded_from_stats: Optional[bool] = None
    counterparty: Optional[str] = None
    reimbursement_type: Optional[str] = None  # corporate | personal_advance


@router.patch("/{transaction_id}/reimbursement")
def update_reimbursement_status(
    transaction_id: uuid.UUID,
    payload: ReimbursementUpdateRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    快捷更新公费报销 / 朋友代垫付状态，一键切换并同步是否不计支出。
    """
    lock_mutation(session)
    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="交易不存在")

    _verify_account_write_permission(session, user_or_ctx, txn.account_id, "修改交易报销状态")
    from services.schedules import guard_transaction
    guard_transaction(txn)

    extra = dict(txn.extra or {})

    if payload.is_reimbursable is not None:
        txn.is_reimbursable = payload.is_reimbursable
    if payload.reimbursement_status is not None:
        txn.reimbursement_status = payload.reimbursement_status
    if payload.excluded_from_stats is not None:
        txn.excluded_from_stats = payload.excluded_from_stats
    if payload.counterparty is not None:
        extra["counterparty"] = payload.counterparty
    if payload.reimbursement_type is not None:
        extra["reimbursement_type"] = payload.reimbursement_type

    txn.extra = extra
    session.add(txn)
    session.commit()
    session.refresh(txn)

    return {
        "ok": True,
        "id": str(txn.id),
        "is_reimbursable": bool(txn.is_reimbursable),
        "reimbursement_status": txn.reimbursement_status,
        "excluded_from_stats": bool(txn.excluded_from_stats),
        "extra": txn.extra,
    }


class TransactionUpdateRequest(BaseModel):
    refund_of_transaction_id: Optional[uuid.UUID] = None
    allocation_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    allocation_currency: Optional[CurrencyCode] = None
    refund_original_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    from_account_id: Optional[uuid.UUID] = None
    to_account_id: Optional[uuid.UUID] = None
    source_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    destination_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    transfer_direction: Optional[Literal['outflow', 'inflow']] = None
    narration: Optional[str] = Field(default=None, max_length=255)
    name: Optional[str] = Field(default=None, max_length=255)
    amount: Optional[Decimal] = Field(default=None, gt=Decimal("0"), max_digits=19, decimal_places=4)
    currency: Optional[CurrencyCode] = None
    original_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    original_currency: Optional[CurrencyCode] = None
    settlement_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    settlement_currency: Optional[CurrencyCode] = None
    master_settlement_amount: Optional[Decimal] = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    master_settlement_currency: Optional[CurrencyCode] = None
    transacted_at: Optional[date] = None
    occurred_at: Optional[datetime] = None
    date: Optional[str] = None
    time: Optional[str] = None
    account_id: Optional[uuid.UUID] = None
    category_id: Optional[Union[uuid.UUID, str]] = None
    transaction_type: Optional[str] = None  # expense | income | transfer | refund
    notes: Optional[str] = None
    is_reimbursable: Optional[bool] = None
    reimbursement_status: Optional[str] = None
    excluded_from_stats: Optional[bool] = None
    counterparty: Optional[Union[str, Dict[str, Any]]] = None
    reimbursement_type: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("date")
    @classmethod
    def validate_calendar_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def validate_time_fields(cls, v: Any):
        return clean_to_utc(v)


@router.put("/{transaction_id}")
@router.patch("/{transaction_id}")
def update_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionUpdateRequest,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    """
    修改交易明细的核心属性：
    交易时间 (日期与时分秒)、分类、账户、记账类型、金额、名称、标签、备注等。
    """
    lock_mutation(session)
    txn = session.get(Transaction, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="交易不存在")

    _verify_account_write_permission(session, user_or_ctx, txn.account_id, "修改交易")
    from services.schedules import guard_transaction
    guard_transaction(txn)

    # 前置校验 1：目标账户合法性与写权限（严禁在校验前进行任何状态修改或提交）
    if "category_id" in payload.model_fields_set:
        from services.refund_money import guard_refund_category_edit
        guard_refund_category_edit(session, txn)

    from services.transfer_editing import normalize_transfer_payload
    normalize_transfer_payload(session, txn, payload)
    target_acc = None
    if payload.account_id is not None:
        target_account_id = None
        if isinstance(payload.account_id, uuid.UUID):
            target_account_id = payload.account_id
        else:
            try:
                target_account_id = uuid.UUID(str(payload.account_id).strip())
            except (ValueError, TypeError):
                target_account_id = None
        if target_account_id and target_account_id != txn.account_id:
            target_acc = session.get(Account, target_account_id)
            if not target_acc:
                raise HTTPException(status_code=400, detail="目标账户不存在")
            old_acc = session.get(Account, txn.account_id)
            if old_acc and target_acc.family_id != old_acc.family_id:
                raise HTTPException(status_code=403, detail="不能跨家庭组迁移流水")
            _verify_account_write_permission(session, user_or_ctx, target_acc.id, "修改流水所属账户")

    # 前置校验 2：transaction_type 枚举校验
    if payload.transaction_type is not None:
        VALID_TXN_TYPES = {"expense", "income", "transfer", "refund"}
        if payload.transaction_type not in VALID_TXN_TYPES:
            raise HTTPException(status_code=400, detail=f"transaction_type 必须是 {sorted(VALID_TXN_TYPES)} 之一")
    resulting_type = payload.transaction_type or txn.transaction_type
    if any(getattr(payload, name) is not None for name in
           ('refund_of_transaction_id', 'allocation_amount', 'allocation_currency', 'refund_original_amount')):
        if resulting_type != 'refund' or payload.refund_of_transaction_id is None:
            raise HTTPException(400, "退款匹配与冲抵额度只能用于指定原消费的退款。")
    if payload.transaction_type and payload.transaction_type != txn.transaction_type:
        if txn.refund_of_transaction_id or session.exec(select(Transaction.id).where(
            Transaction.refund_of_transaction_id == txn.id)).first():
            raise HTTPException(400, "请先解除退款关联，再切换交易类型。")
        if resulting_type not in {'expense', 'refund'} and session.exec(select(TransactionSplit.id).where(
            TransactionSplit.transaction_id == txn.id)).first():
            raise HTTPException(400, "请先解除分类拆分，再切换交易类型。")

    from models import RefundAllocation
    financial = any(getattr(payload, name, None) is not None and getattr(payload, name) != getattr(txn, name, None)
                    for name in ("amount", "currency", "account_id", "original_amount", "original_currency", "transacted_at")) or any(
                        getattr(payload, name, None) is not None for name in ("settlement_amount", "master_settlement_amount")) or (payload.date is not None and date.fromisoformat(payload.date) != txn.transacted_at) or (payload.occurred_at is not None and get_local_date(payload.occurred_at) != txn.transacted_at)
    if financial and session.exec(select(RefundAllocation.id).where(
            or_(RefundAllocation.refund_transaction_id == txn.id, RefundAllocation.original_transaction_id == txn.id))).first():
        raise HTTPException(400, "已参与退款分配的流水，请先解除关联再修改金额、币种、日期或账户")
    original_book = txn.amount
    original_native = txn.original_amount
    original_code = txn.original_currency
    from services.transfer_editing import validate_transfer_edit, apply_transfer_edit
    transfer_edit = validate_transfer_edit(session, user_or_ctx, txn, payload, target_acc,
                                           _verify_account_write_permission)

    if txn.transfer_id:
        if payload.transaction_type is not None and payload.transaction_type != "transfer":
            raise HTTPException(status_code=400, detail="该流水已配对为转账，修改收支类型前请先在转账列表解除配对")

    if payload.amount is not None:
        new_amt = abs(Decimal(str(payload.amount)))
        if new_amt <= Decimal("0"):
            raise HTTPException(status_code=400, detail="交易金额必须大于 0")

        # 1. 拆分明细一致性：若已存在拆分明细，禁止直接修改父交易总金额
        existing_splits = session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)).all()
        if existing_splits and new_amt != txn.amount:
            raise HTTPException(
                status_code=400,
                detail="该流水已存在多分类拆分明细，禁止直接修改总金额。请先在拆分管理中调整拆分子项，或解除拆分后再修改总额。"
            )

    if payload.transaction_type is not None:
        if payload.transaction_type != txn.transaction_type:
            from models import RefundAllocation
            has_alloc = session.exec(select(RefundAllocation).where(
                or_(RefundAllocation.refund_transaction_id == txn.id, RefundAllocation.original_transaction_id == txn.id)
            )).first()
            if has_alloc:
                raise HTTPException(status_code=400, detail="该流水已参与退款冲抵关联，修改收支类型前请先解除所有退款绑定")
        changed_type = payload.transaction_type != txn.transaction_type
        txn.transaction_type = payload.transaction_type
        txn.extra = {**(txn.extra or {}), "transaction_type_source": "manual"}
        if changed_type and txn.transaction_type != "transfer":
            txn.extra = {**txn.extra, "direction": "inflow" if txn.transaction_type in {"income", "refund"} else "outflow"}
    if payload.narration is not None or payload.name is not None:
        txn.narration = payload.narration if payload.narration is not None else payload.name
        txn.merchant_source = "manual"
    if payload.notes is not None:
        txn.notes = payload.notes
    if payload.tags is not None:
        txn.tags = [str(t).strip() for t in payload.tags if str(t).strip()]

    if "category_id" in payload.model_fields_set:
        txn.category_source = "manual"
        txn.extra = {k: v for k, v in (txn.extra or {}).items() if k != "classification"}
        acc = target_acc or session.get(Account, txn.account_id)
        if payload.category_id:
            from services.rules.categories import resolve_category
            try:
                txn.category_id = resolve_category(session, payload.category_id, acc.family_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
        else:
            from services.rules.categories import other_category
            txn.category_id = other_category(session, acc.family_id, create=True).id

    # 处理账户变更
    if target_acc:
        txn.account_id = target_acc.id

    # 处理交易时间 (日期 + 时分秒)
    new_occurred_at = payload.occurred_at
    if not new_occurred_at and payload.date and payload.time:
        try:
            new_occurred_at = clean_to_utc(f"{payload.date.strip()}T{payload.time.strip()}")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    elif not new_occurred_at and (payload.transacted_at or payload.date):
        try:
            tz_local = ZoneInfo("Asia/Shanghai")
            old_local_dt = txn.occurred_at.replace(tzinfo=timezone.utc).astimezone(tz_local) if txn.occurred_at else None
            old_local_time = old_local_dt.time() if old_local_dt else datetime.now().time()
            calendar_date = payload.transacted_at or date.fromisoformat(payload.date)
            new_occurred_at = datetime.combine(calendar_date, old_local_time).replace(tzinfo=tz_local).astimezone(timezone.utc)
        except Exception:
            pass

    if new_occurred_at:
        txn.occurred_at = new_occurred_at.replace(tzinfo=None)
        txn.transacted_at = get_local_date(new_occurred_at)
    elif payload.transacted_at:
        txn.transacted_at = payload.transacted_at

    with session.no_autoflush:
        account = target_acc or session.get(Account, txn.account_id)
        if payload.currency is not None and payload.currency != account.currency:
            raise HTTPException(400, "记账币种必须与账户币种一致，原币请填写 original_currency")
        if financial:
            if (payload.original_amount is None) != (payload.original_currency is None):
                raise HTTPException(422, "请同时填写已核实的原币金额和币种")
            native = payload.original_amount or original_native
            code = payload.original_currency or original_code
            if native is None or code is None:
                if payload.amount is None and not target_acc and payload.settlement_amount is None:
                    pass  # Changing a legacy date does not invent its original currency.
                else:
                    raise HTTPException(409, "历史流水需先确认 original_amount、original_currency 和实际结算金额")
            else:
                if code == account.currency and payload.amount is not None and payload.original_amount is None:
                    native = payload.amount
                bank_amount, bank_code = payload.settlement_amount, payload.settlement_currency
                if bank_amount is None and payload.amount is not None and code != account.currency and not target_acc:
                    bank_amount, bank_code = payload.amount, account.currency
                if bank_amount is None and not target_acc and payload.original_amount is None and original_code == code:
                    bank_amount, bank_code = original_book if payload.amount is None else payload.amount, account.currency
                from services.booking_money import assign_booking
                fields = prepare_booking(session, account, native, code, txn.transacted_at,
                                         bank_amount, bank_code, payload.master_settlement_amount,
                                         payload.master_settlement_currency, "manual_confirmation", occurred_at=txn.occurred_at)
                existing_splits = session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == txn.id)).all()
                if existing_splits and fields["amount"] != original_book:
                    raise HTTPException(400, "换汇后的总额改变，请先解除分类拆分")
                assign_booking(txn, fields)

    # 处理报销相关配置
    extra = dict(txn.extra or {})
    if payload.is_reimbursable is not None:
        txn.is_reimbursable = payload.is_reimbursable
        if not payload.is_reimbursable:
            extra.pop("reimbursement_type", None)
            extra.pop("counterparty", None)
            txn.reimbursement_status = None
    if payload.reimbursement_type is not None:
        extra["reimbursement_type"] = payload.reimbursement_type
        if txn.is_reimbursable is None or not txn.is_reimbursable:
            txn.is_reimbursable = True
    if payload.counterparty is not None:
        if isinstance(payload.counterparty, dict):
            cp_name = payload.counterparty.get("name") or str(payload.counterparty)
        else:
            cp_name = str(payload.counterparty).strip()
        extra["counterparty"] = cp_name
    txn.extra = extra

    if payload.reimbursement_status is not None:
        txn.reimbursement_status = payload.reimbursement_status
    if payload.excluded_from_stats is not None:
        txn.excluded_from_stats = payload.excluded_from_stats

    txn.updated_at = datetime.now(timezone.utc)
    session.add(txn)
    apply_transfer_edit(session, txn, payload, transfer_edit)
    if txn.transaction_type == "refund":
        from services.refund_money import auto_allocate
        auto_allocate(session, user_or_ctx, txn, payload.refund_of_transaction_id,
                      payload.allocation_amount, payload.allocation_currency, payload.refund_original_amount)
    session.commit()
    session.refresh(txn)

    return get_transaction_detail(transaction_id, session=session, user_or_ctx=user_or_ctx)


@router.delete("/{transaction_id}")
def delete_transaction(
    transaction_id: uuid.UUID,
    scope: Optional[Literal["single", "pair"]] = None,
    expected_transfer_id: Optional[uuid.UUID] = None,
    session: Session = Depends(get_session),
    user_or_ctx: Any = Depends(get_current_user_or_token),
):
    from services.transaction_deletion import delete_transactions
    return delete_transactions(session, user_or_ctx, transaction_id, scope,
                               expected_transfer_id, _verify_account_write_permission)
