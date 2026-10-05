"""Family-scoped category references; no merchant keyword classifier."""
import uuid
from sqlmodel import select
from models import Category


def category_path(category, categories):
    path, seen = [], set()
    while category:
        if category.id in seen or len(path) >= 12:
            raise ValueError('分类层级存在循环或超过限制')
        seen.add(category.id)
        path.insert(0, category.name)
        category = categories.get(category.parent_id)
    return path


def resolve_category(session, value, family_id, create=False):
    if not family_id:
        raise ValueError('分类必须属于当前家庭')
    categories = session.exec(select(Category).where(Category.family_id == family_id)).all()
    if isinstance(value, dict):
        path = value.get('path')
        if not isinstance(path, list) or not path:
            raise ValueError('分类引用必须包含 path')
        mapping = {c.id: c for c in categories}
        matches = [c for c in categories if category_path(c, mapping) == path]
    else:
        text = str(value or '').strip()
        try:
            identifier = uuid.UUID(text)
        except (ValueError, TypeError):
            matches = [c for c in categories if c.name == text or c.i18n_key == text]
        else:
            matches = [c for c in categories if c.id == identifier]
    if len(matches) != 1:
        raise ValueError('分类不存在、名称有歧义或属于其他家庭；请先创建分类')
    return matches[0].id


def other_category(session, family_id, create=False):
    category = session.exec(select(Category).where(
        Category.family_id == family_id, Category.name == '其他', Category.parent_id.is_(None)
    )).first()
    if category is None and create and family_id:
        category = Category(family_id=family_id, name='其他', icon='📦', color='#f97316')
        session.add(category)
        session.flush()
    return category
