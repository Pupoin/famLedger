"""Stable label resolution preserves references in private transaction history."""
from sqlmodel import select
from models import Tag


def tag_resolver(session, family_id):
    mapping = {}
    for tag in session.exec(select(Tag).where(Tag.family_id == family_id)).all():
        for name in [tag.name, *(tag.aliases or [])]:
            mapping[name] = None if tag.is_archived else tag.name

    def resolve(names):
        result = []
        for value in names or []:
            if not isinstance(value, str):
                continue
            name = value.strip()
            label = mapping.get(name, name)
            if label and label not in result:
                result.append(label)
        return result
    return resolve
