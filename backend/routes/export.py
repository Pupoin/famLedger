from datetime import date
from io import BytesIO
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlmodel import Session, select
import openpyxl

from auth import get_current_user_or_token
from database import get_session
from models import Account, Category, Family, Transaction, User
from utils import escape_like as _escape_like

router = APIRouter()


def _resolve_user_family_id(session: Session, user_or_ctx: any) -> Optional[uuid.UUID]:
    from services.principals import resolve_family_id
    return resolve_family_id(session, user_or_ctx)

@router.get("/export")
@router.get("/export/csv")
def export_transactions(
    request: Request,
    search: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    sort: Optional[str] = "desc",
    sort_by: Optional[str] = "date",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    session: Session = Depends(get_session),
    current_user_ctx: any = Depends(get_current_user_or_token),
):
    """
    导出当前家庭真实交易流水为 Excel (.xlsx) 表格。
    """
    is_service = isinstance(current_user_ctx, str) and current_user_ctx.startswith("service:")
    current_user = None
    if isinstance(current_user_ctx, str) and not is_service:
        current_user = session.exec(select(User).where(User.username == current_user_ctx)).first()

    family_id = _resolve_user_family_id(session, current_user_ctx)
    if not family_id:
        accounts = []
    else:
        is_admin = is_service or (current_user and current_user.role == "admin")
        all_family_accs = session.exec(select(Account).where(Account.family_id == family_id)).all()
        if is_admin:
            accounts = all_family_accs
        elif current_user:
            # 严格遵循显式授权原则：普通家庭 owner 与普通成员仅能导出授权给本人的账户
            from services.stats_engine import get_user_visible_account_ids
            visible_acc_ids = get_user_visible_account_ids(session, current_user, family_id=family_id)
            accounts = [a for a in all_family_accs if a.id in visible_acc_ids]
        else:
            accounts = []

    acc_map = {a.id: a.name for a in accounts}
    family_acc_ids = list(acc_map.keys())

    # 分类映射
    cats = session.exec(select(Category)).all()
    cat_map = {c.id: c.name for c in cats}

    if not family_acc_ids:
        txns = []
    else:
        statement = select(Transaction).where(Transaction.account_id.in_(family_acc_ids))

        if search:
            escaped = _escape_like(search)
            statement = statement.where(
                or_(
                    Transaction.narration.like(f"%{escaped}%", escape="\\"),
                    Transaction.notes.like(f"%{escaped}%", escape="\\"),
                )
            )
        if category:
            values = [value.strip() for value in category.split(",") if value.strip()]
            all_cats = session.exec(select(Category).where(Category.family_id == family_id)).all()
            matched_ids = {cat.id for cat in all_cats if
                           str(cat.id) in values or cat.name in values or cat.i18n_key in values}
            if not matched_ids:
                raise HTTPException(422, "所指定的导出分类不存在")
            statement = statement.where(Transaction.category_id.in_(matched_ids))
        if transaction_type:
            statement = statement.where(Transaction.transaction_type == transaction_type)
        if start_date:
            statement = statement.where(Transaction.transacted_at >= start_date)
        if end_date:
            statement = statement.where(Transaction.transacted_at <= end_date)

        order_col = Transaction.amount if sort_by == "amount" else Transaction.transacted_at
        statement = statement.order_by(order_col.desc()) if sort == "desc" else statement.order_by(order_col.asc())

        txns = session.exec(statement).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Transactions"

    headers = ["ID", "交易日期", "收支类型", "金额", "币种", "账户", "分类", "标签", "交易摘要", "备注"]
    ws.append(headers)

    # 样式设置
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)

    type_map = {
        "expense": "支出",
        "income": "收入",
        "transfer_out": "转出",
        "transfer_in": "转入",
        "refund": "退款",
    }

    def _sanitize_excel_cell(val: Any) -> Any:
        if isinstance(val, str) and val and val[0] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + val
        return val

    from services.tags import tag_resolver
    resolve_tags = tag_resolver(session, family_id)
    for t in txns:
        c_name = cat_map.get(t.category_id, "未分类") if t.category_id else "未分类"
        tags_str = ", ".join(resolve_tags(t.tags)) if t.tags and isinstance(t.tags, list) else ""
        date_str = str(t.transacted_at)
        row_vals = [
            str(t.id),
            date_str,
            type_map.get(t.transaction_type, t.transaction_type),
            float(t.amount),
            t.currency,
            acc_map.get(t.account_id, "未知账户"),
            c_name,
            tags_str,
            t.narration or "",
            t.notes or "",
        ]
        ws.append([_sanitize_excel_cell(v) for v in row_vals])

    # 自动列宽
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 4, 12), 45)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.spreadsheet",
        headers={"Content-Disposition": f"attachment; filename=transactions_{date.today().isoformat()}.xlsx"},
    )
