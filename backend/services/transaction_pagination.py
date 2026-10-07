"""Database keyset paging, using the exact same newest-first tie breakers."""
from uuid import UUID

from sqlalchemy import tuple_
from sqlmodel import select, func

from models import Transaction


def transaction_page(session, statement, limit, cursor=None, offset=None):
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    if isinstance(cursor, str) and cursor.strip():
        try:
            key = UUID(cursor.strip())
        except ValueError:
            key = None
        # The anchor must satisfy the same authorization and filter scope.
        anchor = session.exec(statement.where(Transaction.id == key)).first() if key else None
        if anchor:
            statement = statement.where(tuple_(Transaction.transacted_at,
                func.coalesce(Transaction.occurred_at, Transaction.created_at), Transaction.created_at, Transaction.id)
                < tuple_(anchor.transacted_at, anchor.occurred_at or anchor.created_at, anchor.created_at, anchor.id))
    elif isinstance(offset, int) and offset > 0:
        statement = statement.offset(offset)
    rows = session.exec(statement.limit(limit + 1)).all()
    return rows[:limit], len(rows) > limit, total
