"""Resolve rule category values within the transaction's family."""
import uuid
from sqlmodel import select
from models import Category
from services.stats_engine import STANDARD_CATEGORY_DEFS


def resolve_category(session, value, family_id, create=False):
    text = str(value or '').strip()
    try:
        category = session.get(Category, uuid.UUID(text))
        if category and category.family_id == family_id:
            return category.id
        raise ValueError('分类不存在或属于其他家庭')
    except (ValueError, TypeError) as exc:
        definition = next((item for item in STANDARD_CATEGORY_DEFS
                           if text == item['id'] or text in item.get('aliases', [])), None)
        if definition is None:
            raise ValueError('分类不存在或属于其他家庭') from exc
        category = session.exec(select(Category).where(Category.family_id == family_id,
                                                        Category.name == definition['name'])).first()
        if category is None and create:
            category = Category(family_id=family_id, name=definition['name'],
                                icon=definition['icon'], color=definition['color'])
            session.add(category)
            session.flush()
        if category is None:
            raise ValueError('预设分类尚未在家庭中创建')
        return category.id
