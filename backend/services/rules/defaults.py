"""One-time migration of user-supplied rules, never a hidden classifier."""
from sqlmodel import select
from models import Account, Category, Family, Rule, Transaction
from .bundles import default_bundle, import_bundle
from .pipeline import RulePipeline


def initialize_family_rules(session, family_id, migrate_history=False):
    family = session.get(Family, family_id)
    if not family or family.classification_rules_version >= 1:
        return
    bundle = default_bundle()
    # Existing rules keep their priorities; imported defaults follow them.
    existing_names = set(session.exec(select(Rule.name).where(Rule.family_id == family_id)).all())
    bundle['rules'] = [r for r in bundle['rules'] if r['name'] not in existing_names]
    import_bundle(session, family_id, bundle)
    family.classification_rules_version = 1
    session.add(family)
    if migrate_history:
        accounts = session.exec(select(Account).where(Account.family_id == family_id)).all()
        names = {a.id: a.name for a in accounts}
        rules = session.exec(select(Rule).where(Rule.family_id == family_id)).all()
        pipeline = RulePipeline(rules, session, classification_only=True)
        if names:
            txns = session.exec(select(Transaction).where(Transaction.account_id.in_(list(names)),
                                                           Transaction.category_source != 'manual')).all()
            for txn in txns:
                if txn.category_id and (txn.extra or {}).get('scheduled_plan_id') and (txn.extra or {}).get('component') in ('interest', 'fee', 'capitalized_interest'):
                    txn.category_source = 'manual'
                pipeline.process_transaction(txn, names[txn.account_id])
                session.add(txn)
    session.flush()


def initialize_existing_families(session):
    families = session.exec(select(Family).where(Family.classification_rules_version < 1)).all()
    for family in families:
        initialize_family_rules(session, family.id, migrate_history=True)
    session.commit()
