import uuid
from decimal import Decimal
from datetime import date, datetime, timezone
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 2. 多用户与会话管理 (User & Session)
# ==========================================
class User(SQLModel, table=True):
    """用户实体。彻底破除 2 人注册上限。"""
    __tablename__ = "users"

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ==========================================
# 5.5. 原始账单邮件归档 (StoredEmail)
# ==========================================
class StoredEmail(SQLModel, table=True):
    """原始账单邮件归档与审计。支持定期拉取与重复解析。"""
    __tablename__ = "stored_emails"
    __table_args__ = (
        Index("uq_stored_email_msgid", "message_id", unique=True),
        Index("uq_stored_email_fingerprint", "content_fingerprint", unique=True),
        Index("ix_stored_emails_status", "status"),
        Index("ix_stored_emails_received", "received_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
    message_id: str = Field(max_length=255, index=True)
    content_fingerprint: str = Field(max_length=128, index=True)
    mail_kind: str = Field(default="other", max_length=50)  # credit_daily | credit_recent | debit | other
    subject: str = Field(max_length=500)
    sender: str = Field(max_length=255)
    recipient: Optional[str] = Field(default=None, max_length=255)
    received_at: datetime = Field(index=True)
    raw_html: Optional[str] = Field(default=None)
    raw_text: Optional[str] = Field(default=None)
    raw_payload: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON_TYPE)
    )
    status: str = Field(default="pending", max_length=30)  # pending | parsed | failed | ignored
    error_message: Optional[str] = Field(default=None)
    parsed_at: Optional[datetime] = Field(default=None)
    parsed_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    raw_email_id: Optional[uuid.UUID] = Field(default=None, foreign_key="stored_emails.id", index=True)
    external_id: Optional[str] = Field(default=None, max_length=255, index=True)
    transacted_at: date = Field(index=True)
    exact_time: Optional[datetime] = Field(default=None)
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
    currency: str = Field(default="CNY", max_length=10)
    name: str = Field(max_length=255)
    merchant_name: Optional[str] = Field(default=None, max_length=150, index=True)
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
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(19, 4)))
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


class PersonalDebt(SQLModel, table=True):
    """亲友私人借贷往来台账。"""
    __tablename__ = "personal_debts"
    __table_args__ = (
        Index("ix_debts_family_status", "family_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    family_id: uuid.UUID = Field(foreign_key="families.id", index=True)
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
# 兼容旧版本模型 (仅用于迁移过渡)
# ==========================================
class ExpenseBase(SQLModel):
    date: date
    description: str = Field(max_length=500)
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(10, 2)))
    category: str = Field(max_length=100)
    paid_by: str
    split_method: str

class Expense(ExpenseBase, table=True):
    __tablename__ = "expense"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[str] = Field(default=None)

class ExpenseCreate(ExpenseBase):
    pass

class ExpenseUpdate(ExpenseBase):
    pass

class DismissedMerge(SQLModel, table=True):
    __tablename__ = "dismissedmerge"
    id: Optional[int] = Field(default=None, primary_key=True)
    category: str = Field(max_length=100)
    desc_a: str = Field(max_length=500)
    desc_b: str = Field(max_length=500)
    dismissed_by: str = Field(max_length=100)

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
}

VALID_DATE_FORMATS = {"DD/MM/YYYY", "MM/DD/YYYY", "YYYY/MM/DD", "YYYY/DD/MM"}
VALID_CURRENCIES = set(CURRENCY_SYMBOLS.keys())
VALID_INCOME_SOURCES = ["Salary", "Freelance", "Investment", "Gift", "Other"]

class IncomeBase(SQLModel):
    date: date
    amount: Decimal = Field(sa_column=Column(sqlalchemy.Numeric(10, 2)))
    source: str
    notes: Optional[str] = Field(default=None, max_length=500)

class Income(IncomeBase, table=True):
    __tablename__ = "income"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)

class IncomeCreate(IncomeBase):
    pass

class IncomeUpdate(IncomeBase):
    pass

class SeriesAlertState(SQLModel, table=True):
    __tablename__ = "series_alert_states"
    __table_args__ = (
        Index("ix_series_alert_lookup", "series_key", "alert_type", unique=True),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
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

class Settings(SQLModel, table=True):
    __tablename__ = "settings"
    id: int = Field(default=1, primary_key=True)
    app_mode: str = Field(default="personal")
