import uuid
from decimal import Decimal
from datetime import date, datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import sqlalchemy
from sqlalchemy import Index, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from pydantic import field_serializer, field_validator
from sqlmodel import SQLModel, Field, Column, Relationship

# 兼容 PostgreSQL 原生 JSONB 与 SQLite 测试/开发 JSON
JSON_TYPE = JSONB().with_variant(sqlalchemy.JSON, "sqlite")

# ==========================================
# 1. 家庭组织实体 (Family)
# ==========================================
class Family(SQLModel, table=True):
    """单家庭核心组织实体。"""
    __tablename__ = "families"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(default="我的家庭", max_length=100)
    currency: str = Field(default="CNY", max_length=10)
    month_start_day: int = Field(default=1, ge=1, le=28)
    default_account_sharing: str = Field(default="shared", max_length=20) # shared | private
    is_solo: bool = Field(default=False) # 兼容标记：是否为单人空间
    kind: str = Field(default="collaborative", max_length=20) # personal(个人独立记账空间) | collaborative(多人协作家庭组)
    status: str = Field(default="active", max_length=20, index=True) # active(活动) | dissolved(已解散归档)
    personal_owner_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    dissolved_at: Optional[datetime] = Field(default=None)
    dissolved_by_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 2. 多用户与会话管理 (User & Session)
# ==========================================
class User(SQLModel, table=True):
    """用户实体。彻底破除 2 人注册上限。"""
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_username_ci", sqlalchemy.func.lower(sqlalchemy.column("username")), unique=True),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: Optional[uuid.UUID] = Field(default=None, foreign_key="families.id", index=True)
    username: str = Field(max_length=50, unique=True, index=True)
    email: Optional[str] = Field(default=None, max_length=255, unique=True, index=True)
    display_name: str = Field(max_length=100, index=True)
    password_hash: Optional[str] = Field(default=None, max_length=200)
    role: str = Field(default="member", max_length=20)  # owner | admin | member | guest
    theme: str = Field(default="system", max_length=20)  # system | light | dark
    locale: str = Field(default="zh-CN", max_length=20)  # zh-CN | en-US
    is_active: bool = Field(default=True)
    stay_signed_in: bool = Field(default=False)
    session_version: int = Field(default=0)
    security_question: Optional[str] = Field(default=None, max_length=300)
    security_answer_hash: Optional[str] = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserSession(SQLModel, table=True):
    """用户多端登录会话管理。"""
    __tablename__ = "sessions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(max_length=128, unique=True, index=True)
    ip_address: Optional[str] = Field(default=None, max_length=50)
    user_agent: Optional[str] = Field(default=None, max_length=500)
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime


class RevokedSession(SQLModel, table=True):
    """Revocation follows the session ID across sliding cookie refreshes."""
    __tablename__ = "revoked_sessions"
    id: str = Field(primary_key=True, max_length=64)
    expires_at: int


class OIDCLogin(SQLModel, table=True):
    __tablename__ = "oidc_logins"
    id: str = Field(primary_key=True, max_length=64)
    provider_id: uuid.UUID = Field(index=True)
    issuer: str
    client_id: str
    redirect_uri: str
    nonce: str
    code_verifier: str
    expires_at: int
    consumed: bool = Field(default=False)


class ExchangeRateSnapshot(SQLModel, table=True):
    """Daily quotes keyed by requested day, retaining the actual business day."""
    __tablename__ = "exchange_rate_snapshots"
    requested_date: date = Field(primary_key=True)
    base_currency: str = Field(default="EUR", primary_key=True, max_length=10)
    effective_date: date
    rates: Dict[str, str] = Field(sa_column=Column(JSON_TYPE, nullable=False))
    provider: str = Field(default="frankfurter", max_length=50)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 3. OIDC / SSO 提供商与身份绑定
# ==========================================
class SSOProvider(SQLModel, table=True):
    """动态 OIDC/SSO 身份提供商配置。"""
    __tablename__ = "sso_providers"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=50, unique=True, index=True)  # 如 authentik, keycloak, google
    label: str = Field(max_length=100)
    issuer: str = Field(max_length=255)
    client_id: str = Field(max_length=255)
    client_secret_encrypted: str = Field(max_length=500)
    enabled: bool = Field(default=True, index=True)
    settings: Dict[str, Any] = Field(
        default_factory=lambda: {"allow_jit": True, "default_role": "member", "allowed_domains": []},
        sa_column=Column(JSON_TYPE)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OIDCIdentity(SQLModel, table=True):
    """用户与外部 OIDC IdP 的身份关联。"""
    __tablename__ = "oidc_identities"
    __table_args__ = (
        Index("uq_oidc_provider_uid", "provider", "uid", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    provider: str = Field(max_length=50)
    uid: str = Field(max_length=255)
    issuer: Optional[str] = Field(default=None, max_length=255)
    info: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON_TYPE)
    )
    last_authenticated_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 4. 账户与细粒度共享 (Account & Shares)
# ==========================================
class Account(SQLModel, table=True):
    """多资产分类资金账户。"""
    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_family_classification", "family_id", "classification"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    owner_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)
    name: str = Field(max_length=100)
    account_type: str = Field(max_length=50)  # checking, savings, credit_card, investment, loan, other
    classification: str = Field(default="asset", max_length=20)  # asset | liability
    currency: str = Field(default="CNY", max_length=10)
    balance: Decimal = Field(default=Decimal("0.00"), sa_column=Column(sqlalchemy.Numeric(19, 4)))
    is_active: bool = Field(default=True, index=True)
    exclude_from_reports: bool = Field(default=False)
    institution_name: Optional[str] = Field(default=None, max_length=100, index=True)
    external_identifier: Optional[str] = Field(default=None, max_length=100, index=True)
    parent_account_id: Optional[uuid.UUID] = Field(default=None, foreign_key="accounts.id", index=True)
    color: Optional[str] = Field(default=None, max_length=50)
    icon: Optional[str] = Field(default=None, max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AccountShare(SQLModel, table=True):
    """细粒度账户共享权限。"""
    __tablename__ = "account_shares"
    __table_args__ = (
        Index("uq_account_user_share", "account_id", "user_id", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    permission: str = Field(default="read_only", max_length=20)  # full_control | read_write | read_only
    include_in_finances: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 5. 分类实体 (Category)
# ==========================================
class Category(SQLModel, table=True):
    """交易分类体系。支持内置 i18n key 与自定义。"""
    __tablename__ = "categories"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    name: str = Field(max_length=100)
    i18n_key: Optional[str] = Field(default=None, max_length=100)  # 如 category.food_dining
    parent_id: Optional[uuid.UUID] = Field(default=None, foreign_key="categories.id")
    icon: Optional[str] = Field(default=None, max_length=50)
    color: Optional[str] = Field(default=None, max_length=30)
    category_type: str = Field(default="expense", max_length=20, index=True)  # expense | income
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 5.2. 标签实体 (Tag)
# ==========================================
class Tag(SQLModel, table=True):
    """交易多维标签体系。每笔交易可拥有多个标签。"""
    __tablename__ = "tags"

    aliases: List[str] = Field(default_factory=list, sa_column=Column(
        JSON_TYPE, nullable=False, server_default=sqlalchemy.text("'[]'")))
    is_archived: bool = Field(default=False)
    __table_args__ = (
        Index("uq_tag_family_name", "family_id", "name", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    name: str = Field(max_length=50)
    color: Optional[str] = Field(default="#71717a", max_length=30)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 6. 统一交易流水与拆分 (Transaction & Split)
# ==========================================
class Transaction(SQLModel, table=True):
    """统一交易流水。"""
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_txn_account_date", "account_id", "transacted_at"),
        Index("uq_account_external_id", "account_id", "external_id", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    external_id: Optional[str] = Field(default=None, max_length=255, index=True)
    transacted_at: date = Field(index=True)
    occurred_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    currency: str = Field(default="CNY", max_length=10)
    narration: str = Field(max_length=255)
    original_amount: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(19, 4)))
    original_currency: Optional[str] = Field(default=None, max_length=10)
    exchange_rate: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(28, 12)))
    exchange_rate_date: Optional[date] = None
    exchange_rate_source: Optional[str] = Field(default=None, max_length=100)
    master_account_id: Optional[uuid.UUID] = Field(default=None, index=True)
    master_settlement_amount: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(19, 4)))
    master_settlement_currency: Optional[str] = Field(default=None, max_length=10)
    master_exchange_rate: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(28, 12)))
    master_exchange_rate_date: Optional[date] = None
    master_exchange_rate_source: Optional[str] = Field(default=None, max_length=100)
    category_id: Optional[uuid.UUID] = Field(default=None, foreign_key="categories.id", index=True)
    transaction_type: str = Field(default="expense", max_length=30, index=True)  # expense | income | transfer | refund | adjustment
    status: str = Field(default="cleared", max_length=20)  # cleared | pending
    transfer_id: Optional[uuid.UUID] = Field(default=None, index=True)
    refund_of_transaction_id: Optional[uuid.UUID] = Field(default=None, foreign_key="transactions.id", index=True)
    is_split: bool = Field(default=False)
    is_reimbursable: bool = Field(default=False)
    reimbursement_status: Optional[str] = Field(default=None, max_length=20)  # unclaimed | claimed | settled
    reconciled: bool = Field(default=False)
    excluded_from_stats: bool = Field(default=False)
    notes: Optional[str] = Field(default=None)
    tags: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSON_TYPE)
    )
    category_source: str = Field(default="import", max_length=20)  # manual | rule | import
    merchant_source: str = Field(default="import", max_length=20)
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON_TYPE)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TransactionSplit(SQLModel, table=True):
    """交易子分拆项。"""
    __tablename__ = "transaction_splits"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transaction_id: uuid.UUID = Field(foreign_key="transactions.id", index=True)
    category_id: Optional[uuid.UUID] = Field(default=None, foreign_key="categories.id")
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    notes: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PendingFxTransaction(SQLModel, table=True):
    """Unbooked source records; a separate table keeps them out of all ledger sums."""
    __tablename__ = "pending_fx_transactions"
    __table_args__ = (Index("uq_pending_fx_external", "account_id", "external_id", unique=True),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    requested_by_user_id: Optional[uuid.UUID] = Field(default=None, index=True)
    requested_by_service: bool = Field(default=False)
    external_id: Optional[str] = Field(default=None, max_length=255)
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON_TYPE))
    status: str = Field(default="pending_fx", max_length=20, index=True)
    posted_transaction_id: Optional[uuid.UUID] = None
    attempts: int = Field(default=0)
    last_error: Optional[str] = Field(default=None, max_length=500)
    retry_after: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 7. 转账与退款关联 (Transfer & Refund)
# ==========================================
class Transfer(SQLModel, table=True):
    """转账双向绑定关联表。"""
    __tablename__ = "transfers"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    outflow_transaction_id: uuid.UUID = Field(foreign_key="transactions.id", unique=True, index=True)
    inflow_transaction_id: uuid.UUID = Field(foreign_key="transactions.id", unique=True, index=True)
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    status: str = Field(default="confirmed", max_length=20)  # pending | confirmed
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RejectedTransfer(SQLModel, table=True):
    """驳回转账黑名单，防止再次静默合并。"""
    __tablename__ = "rejected_transfers"
    __table_args__ = (
        Index("uq_rejected_pair", "outflow_transaction_id", "inflow_transaction_id", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    outflow_transaction_id: uuid.UUID = Field(foreign_key="transactions.id", index=True)
    inflow_transaction_id: uuid.UUID = Field(foreign_key="transactions.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RefundAllocation(SQLModel, table=True):
    """退款冲抵多对多关联分配表。"""
    __tablename__ = "refund_allocations"
    __table_args__ = (
        Index("uq_refund_pair", "refund_transaction_id", "original_transaction_id", unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    refund_transaction_id: uuid.UUID = Field(foreign_key="transactions.id", index=True)
    original_transaction_id: uuid.UUID = Field(foreign_key="transactions.id", index=True)
    allocated_amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    original_currency: Optional[str] = Field(default=None, max_length=10)
    original_book_amount: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(19, 4)))
    original_book_currency: Optional[str] = Field(default=None, max_length=10)
    refund_original_amount: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(19, 4)))
    refund_original_currency: Optional[str] = Field(default=None, max_length=10)
    refund_book_amount: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(19, 4)))
    refund_book_currency: Optional[str] = Field(default=None, max_length=10)
    fx_difference_amount: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(19, 4)))
    fx_difference_currency: Optional[str] = Field(default=None, max_length=10)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 8. 高级规则引擎 (Rules Engine)
# ==========================================
class Rule(SQLModel, table=True):
    """基于 Specification + Composite + Command 的规则实体。"""
    __tablename__ = "rules"
    __table_args__ = (
        Index("ix_rules_priority", "family_id", "priority"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    name: str = Field(max_length=150)
    description: Optional[str] = Field(default=None, max_length=500)
    priority: int = Field(default=100)
    is_active: bool = Field(default=True, index=True)
    enabled: bool = Field(default=True)
    stop_processing: bool = Field(default=False)
    allow_override_manual: bool = Field(default=False)
    conditions: Dict[str, Any] = Field(
        sa_column=Column(JSON_TYPE)
    )
    actions: List[Dict[str, Any]] = Field(
        sa_column=Column(JSON_TYPE)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 9. 贷款与私人借据 (Loans & Personal Debts)
# ==========================================
class Loan(SQLModel, table=True):
    """金融机构贷款与还款测算。"""
    __tablename__ = "loans"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", unique=True, index=True)
    loan_type: str = Field(default="mortgage", max_length=30)  # mortgage, auto, consumer, other
    original_amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    term_months: int
    interest_rate: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(10, 4)))
    repayment_method: str = Field(default="equal_installment", max_length=30)  # equal_installment | equal_principal
    monthly_payment: Optional[Decimal] = Field(default=None, sa_column=Column(sqlalchemy.Numeric(19, 4)))
    lender_name: Optional[str] = Field(default=None, max_length=100)
    start_date: date
    end_date: Optional[date] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScheduledPlan(SQLModel, table=True):
    __tablename__ = "scheduled_plans"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    owner_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    destination_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    accrual_account_id: Optional[uuid.UUID] = Field(default=None, foreign_key="accounts.id")
    kind: str = Field(max_length=20)
    name: str = Field(max_length=100)
    currency: str = Field(max_length=10)
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    start_date: date
    end_date: Optional[date] = None
    frequency: str = Field(default="monthly", max_length=20)
    interval: int = Field(default=1)
    occurrence_limit: int = Field(default=120)
    timezone_name: str = Field(default="UTC", max_length=100)
    execution_mode: str = Field(default="confirm", max_length=20)
    status: str = Field(default="active", max_length=20, index=True)
    config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON_TYPE, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScheduledOccurrence(SQLModel, table=True):
    __tablename__ = "scheduled_occurrences"
    __table_args__ = (
        Index("uq_plan_installment", "plan_id", "number", unique=True),
        Index("uq_scheduled_bank_id", "account_id", "bank_external_id", unique=True),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    plan_id: uuid.UUID = Field(foreign_key="scheduled_plans.id", index=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    number: int
    due_date: date = Field(index=True)
    status: str = Field(default="planned", max_length=20)
    snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON_TYPE, nullable=False))
    transaction_ids: List[str] = Field(default_factory=list, sa_column=Column(JSON_TYPE, nullable=False))
    transfer_ids: List[str] = Field(default_factory=list, sa_column=Column(JSON_TYPE, nullable=False))
    bank_external_id: Optional[str] = Field(default=None, max_length=255)
    linked_transaction_id: Optional[uuid.UUID] = None
    linked_original: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON_TYPE, nullable=False))
    last_error: Optional[str] = Field(default=None, max_length=500)
    posted_at: Optional[datetime] = None
    retry_after: Optional[datetime] = None


class ScheduledBankMatch(SQLModel, table=True):
    __tablename__ = "scheduled_bank_matches"
    __table_args__ = (Index("uq_scheduled_bank_match", "account_id", "external_id", unique=True),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    occurrence_id: uuid.UUID = Field(foreign_key="scheduled_occurrences.id", index=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    external_id: str = Field(max_length=255)
    transaction_id: uuid.UUID = Field(foreign_key="transactions.id")


class PersonalDebt(SQLModel, table=True):
    """亲友私人借贷往来台账。"""
    __tablename__ = "personal_debts"
    __table_args__ = (
        Index("ix_debts_family_status", "family_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    owner_id: Optional[uuid.UUID] = Field(default=None, index=True)
    debt_type: str = Field(max_length=20)  # lend | borrow
    counterparty: str = Field(max_length=100)
    principal_amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    remaining_amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    currency: str = Field(default="CNY", max_length=10)
    borrowed_date: date
    due_date: Optional[date] = Field(default=None)
    interest_rate: Decimal = Field(default=Decimal("0.00"), sa_column=Column(sqlalchemy.Numeric(10, 4)))
    status: str = Field(default="active", max_length=20)  # active | settled | written_off
    notes: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 10. 资产动态估值 (Valuations)
# ==========================================
class Valuation(SQLModel, table=True):
    """投资与固定资产历史市值估值表。"""
    __tablename__ = "valuations"
    __table_args__ = (
        Index("ix_valuations_account_date", "account_id", "valuation_date"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="accounts.id", index=True)
    valuation_date: date
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    currency: str = Field(default="CNY", max_length=10)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 财务洞察计算使用的非持久化投影模型（不建表）
# ==========================================
class ExpenseBase(SQLModel):
    date: date
    description: str = Field(default="", max_length=500)
    amount: Decimal = Field(default=Decimal("0"))
    category: str = Field(default="", max_length=100)
    paid_by: str = Field(default="")
    split_method: str = Field(default="Personal")

class Expense(ExpenseBase):
    id: Optional[int] = Field(default=None)
    user_id: Optional[str] = Field(default=None)

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "C$",
    "AUD": "A$",
    "INR": "₹",
    "JPY": "¥",
    "CNY": "¥",
    "CHF": "CHF",
    "SGD": "S$",
    "HKD": "HK$",
}

VALID_DATE_FORMATS = {"DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "YYYY/DD/MM"}
VALID_CURRENCIES = set(CURRENCY_SYMBOLS.keys())

class IncomeBase(SQLModel):
    date: date
    amount: Decimal = Field(default=Decimal("0"))
    source: str = Field(default="")
    notes: Optional[str] = Field(default=None, max_length=500)

class Income(IncomeBase):
    id: Optional[int] = Field(default=None)
    user_id: str = Field(default="")

class SeriesAlertState(SQLModel, table=True):
    __tablename__ = "series_alert_states"
    __table_args__ = (
        Index("ix_series_alert_lookup", "series_key", "alert_type", "family_id", unique=True),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    family_id: Optional[uuid.UUID] = Field(default=None, index=True)
    series_key: str = Field(max_length=600)
    alert_type: str = Field(max_length=30)
    first_seen: date = Field(default_factory=date.today)
    last_seen: date = Field(default_factory=date.today)
    dismissed: bool = Field(default=False)
    dismissed_by: Optional[str] = Field(default=None, max_length=100)
    dismissed_at: Optional[datetime] = Field(default=None)
    baseline_amount: Optional[Decimal] = Field(
        default=None, sa_column=Column(sqlalchemy.Numeric(10, 2))
    )

class UserPreference(SQLModel, table=True):
    __tablename__ = "userpreference"
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(max_length=100, unique=True, index=True)
    date_format: str = Field(default="YYYY-MM-DD", max_length=20)
    currency: str = Field(default="CNY", max_length=10)
    income_mode_enabled: bool = Field(default=False)
    has_chosen_currency: bool = Field(default=True)
    language: str = Field(default='en', max_length=10)
    has_chosen_language: bool = Field(default=True)

class Settings(SQLModel, table=True):
    __tablename__ = "settings"
    id: int = Field(default=1, primary_key=True)
    app_mode: str = Field(default="personal")


# ==========================================
# 16. API 密钥管理实体 (ApiKey)
# ==========================================
class ApiKey(SQLModel, table=True):
    """用户个人 API Key，支持自动化脚本、快捷指令与外部系统安全鉴权。"""
    __tablename__ = "api_keys"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=100)  # 例如 "iOS 快捷指令"、"自动化记账脚本"
    key_prefix: str = Field(max_length=16, index=True)  # 例如 "flk_live_a1b2"
    hashed_key: str = Field(max_length=64, unique=True, index=True)  # SHA-256 哈希
    scopes: str = Field(default="*")  # 权限范围，默认 "*" 全权限
    expires_at: Optional[datetime] = Field(default=None)
    last_used_at: Optional[datetime] = Field(default=None)
    is_revoked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



class FamilyBudget(SQLModel, table=True):
    __tablename__ = "family_budgets"
    family_id: uuid.UUID = Field(foreign_key="families.id", primary_key=True)
    settings: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON_TYPE))


class FamilyInvitation(SQLModel, table=True):
    """家庭组入组邀请记录表。"""
    __tablename__ = "family_invitations"
    __table_args__ = (
        Index("ix_invitation_family_invitee", "family_id", "invitee_user_id"),
        Index("ix_invitation_invitee_status", "invitee_user_id", "status"),
        Index("uq_pending_family_invitation", "family_id", "invitee_user_id", unique=True,
              sqlite_where=sqlalchemy.text("status = 'pending'"),
              postgresql_where=sqlalchemy.text("status = 'pending'")),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    inviter_user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    invitee_user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member", max_length=20)  # 普通入组邀请固定为 member 角色
    status: str = Field(default="pending", max_length=20, index=True)  # pending | accepted | rejected | canceled | expired
    message: Optional[str] = Field(default=None, max_length=200)  # 邀请附言
    source_family_id_at_issue: Optional[uuid.UUID] = Field(default=None)  # 发起时受邀人的源家庭
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=7))
    processed_at: Optional[datetime] = Field(default=None)
    processed_by_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    cancel_reason: Optional[str] = Field(default=None, max_length=200)
