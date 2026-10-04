"""Committed database changes trigger backups, independently of audit logging."""
import logging
from sqlalchemy import event
from sqlalchemy.orm import Session

_listener = None

def set_listener(listener):
    global _listener
    _listener = listener

@event.listens_for(Session, 'after_flush')
def _changed(session, context):
    if session.new or session.dirty or session.deleted:
        session.info['committed_mutation_pending'] = True

@event.listens_for(Session, 'after_rollback')
def _rolled_back(session):
    session.info.pop('committed_mutation_pending', None)

@event.listens_for(Session, 'after_commit')
def _committed(session):
    changed = session.info.pop('committed_mutation_pending', False)
    if changed and _listener:
        try:
            _listener()
        except Exception:
            logging.getLogger('mosaic').exception('Committed data change backup failed')
