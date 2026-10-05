from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock
import hashlib
import json

import pytest

from backend.config import parse_replay_setting
from backend.ingest import famledger_sync, pipeline
from backend.ingest.mail_store import MailStore
from backend.ingest.models import TransactionRecord
from test_pipeline import message, setup_pipeline


@pytest.mark.parametrize('value,expected', [
    ('', ('', 0)), (None, ('', 0)), (' 10d@run-1 ', ('10d@run-1', 10)),
    ('all@restore-20261004', ('all@restore-20261004', 0)),
    ('ALL@Run_2', ('all@Run_2', 0)), ('36500d@maximum', ('36500d@maximum', 36500)),
])
def test_single_replay_setting_combines_scope_and_request(value, expected):
    assert parse_replay_setting(value) == expected


@pytest.mark.parametrize('value', ['10', '10d', '10@run', '0d@run', '-1d@run', '10d@',
                                   '10d@run with spaces', '36501d@run', 'all@' + 'a' * 65])
def test_invalid_replay_settings_are_rejected(value):
    with pytest.raises(ValueError, match='MAILBRIDGE_REPLAY'):
        parse_replay_setting(value)


def record(when):
    return TransactionRecord(cost_time=when, cost=Decimal('-10'), account='0007', business='Store',
                             behaviour='消费', original_currency='CNY', account_type='credit_card')


def test_replay_filters_transaction_times_including_edges_not_email_received_date(monkeypatch):
    end = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    start = end - timedelta(days=10)
    rows = [record(start - timedelta(seconds=1)), record(start), record(end - timedelta(days=2)),
            record(end), record(end + timedelta(seconds=1))]
    monkeypatch.setattr(famledger_sync, 'parse_credit_recent_message', lambda _: rows)
    client = Mock()
    client.push_transaction.return_value = {'status': 'duplicate'}
    msg = message()
    assert famledger_sync.sync_emails_and_parse_to_famledger(
        client, {'credit_recent': [msg]}, since=start, until=end) == (1, 0)
    assert [call.args[0] for call in client.push_transaction.call_args_list] == rows[1:4]


def test_ranged_replay_keeps_normal_acknowledgements_and_resumes_fixed_window(monkeypatch, tmp_path):
    end = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    old, recent = record(end - timedelta(days=20)), record(end - timedelta(days=2))
    monkeypatch.setattr(famledger_sync, 'parse_credit_recent_message', lambda _: [old, recent])
    client = Mock()
    client.push_transaction.return_value = {'status': 'duplicate'}
    path = tmp_path / 'mail.db'
    with MailStore(path) as store:
        store.save_message('source', 'credits', 'credit_recent', message())
        store.mark_delivery('source', 'mail-1', 'normal')
        window = store.prepare_ranged_replay('source', 'normal', '10d@first', 10, now=end)
        result = pipeline.deliver_cached(store, 'source', window['target'], client, window=window)
        assert result[:3] == (1, 0, 0)
        assert client.push_transaction.call_args.args[0] == recent
        normal = store.conn.execute("SELECT status,attempts FROM deliveries WHERE target_key='normal'").fetchone()
        assert tuple(normal) == ('sent', 1)
    with MailStore(path) as store:
        resumed = store.prepare_ranged_replay('source', 'normal', '10d@first', 10, now=end + timedelta(days=3))
        assert resumed == window
        assert pipeline.deliver_cached(store, 'source', resumed['target'], client, window=resumed)[:3] == (0, 0, 0)
        assert client.push_transaction.call_count == 1
        next_window = store.prepare_ranged_replay('source', 'normal', '10d@second', 10, now=end + timedelta(days=1))
        assert next_window['target'] != window['target']
        assert pipeline.deliver_cached(store, 'source', next_window['target'], client, window=next_window)[:3] == (1, 0, 0)
        assert client.push_transaction.call_count == 2


def test_pipeline_replays_range_once_and_passes_durable_time_bounds(monkeypatch, tmp_path):
    cfg, _, token, post = setup_pipeline(monkeypatch, tmp_path)
    assert pipeline.run() == (1, 1)
    cfg.replay_id, cfg.replay_days = '10d@retry-1', 10
    post.reset_mock()
    post.return_value = (1, 0)
    token.reset_mock()
    assert pipeline.run(fetch_new=False) == (1, 0)
    filters = post.call_args.kwargs
    assert filters['until'] - filters['since'] == timedelta(days=10)
    assert pipeline.run(fetch_new=False) == (0, 0)
    assert post.call_count == 1
    token.assert_not_called()


def test_range_replay_failure_retries_without_resetting_normal_or_completed_mail(monkeypatch, tmp_path):
    from backend.ingest.famledger_sync import DeliveryBlocked
    cfg, graph, _, post = setup_pipeline(monkeypatch, tmp_path)
    graph.delta_messages.side_effect = lambda folder, delta: ([message('one'), message('two')] if folder == 'debit' else [], 'https://graph.microsoft.com/delta/' + folder)
    assert pipeline.run() == (2, 2)
    cfg.replay_id, cfg.replay_days = '10d@retry-1', 10
    post.reset_mock()
    post.side_effect = [(1, 0), DeliveryBlocked('Target offline')]
    with pytest.raises(pipeline.PendingDeliveryError):
        pipeline.run(fetch_new=False)
    first_bounds = post.call_args_list[0].kwargs
    post.side_effect = None
    post.return_value = (1, 0)
    assert pipeline.run(fetch_new=False) == (1, 0)
    assert post.call_args.kwargs == first_bounds
    assert pipeline.run(fetch_new=False) == (0, 0)
    assert post.call_count == 3
    with MailStore(cfg.database_path) as store:
        normal = store.conn.execute("SELECT attempts FROM deliveries WHERE target_key NOT LIKE 'replay:%'").fetchall()
        assert [row[0] for row in normal] == [1, 1]


def test_normal_pending_delivery_is_not_limited_by_manual_replay_window(monkeypatch, tmp_path):
    cfg, _, _, post = setup_pipeline(monkeypatch, tmp_path)
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        store.save_message(source, 'debit', 'debit', message())
        store.mark_delivery(source, 'mail-1', hashlib.sha256(
            json.dumps([cfg.api_url, cfg.api_token]).encode()).hexdigest(), 'old failure')
    cfg.replay_id, cfg.replay_days = '10d@retry-1', 10
    assert pipeline.run(fetch_new=False) == (2, 2)
    assert post.call_args_list[0].kwargs == {}
    assert 'since' in post.call_args_list[1].kwargs


@pytest.mark.parametrize('setting,days', [('all@deferred', 0), ('10d@deferred', 10)])
def test_post_pause_preserves_replay_and_delivery_state_until_post_only_resume(monkeypatch, tmp_path, setting, days):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    assert pipeline.run() == (1, 1)
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        before = '\n'.join(store.conn.iterdump())
    cfg.post_enabled = False
    cfg.replay_id, cfg.replay_days = setting, days
    post.reset_mock()
    # Existing cached mail is still found, but replay and sent receipts are untouched.
    assert pipeline.run() == (0, 0)
    post.assert_not_called()
    with MailStore(cfg.database_path) as store:
        assert [tuple(row) for row in store.conn.execute('SELECT status,attempts FROM deliveries')] == [('sent', 1)]
        assert setting not in '\n'.join(store.conn.iterdump())
        assert setting not in before
        assert store.contains(source, 'mail-1')
    cfg.pull_enabled = False
    cfg.post_enabled = True
    token.reset_mock()
    graph.reset_mock()
    post.return_value = (1, 0)
    assert pipeline.run() == (1, 0)
    assert post.call_count == 1
    if days:
        bounds = post.call_args.kwargs
        assert bounds['until'] - bounds['since'] == timedelta(days=days)
    else:
        assert post.call_args.kwargs == {}
    assert pipeline.run() == (0, 0)
    assert post.call_count == 1
    token.assert_not_called()
    assert graph.mock_calls == []


def test_pull_only_new_mail_is_delivered_normally_outside_replay_range_when_post_resumes(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    assert pipeline.run() == (1, 1)
    cfg.post_enabled = False
    cfg.replay_id, cfg.replay_days = '10d@deferred', 10
    graph.delta_messages.side_effect = lambda folder, delta: (
        [message('new-mail')] if folder == 'debit' else [], 'https://graph.microsoft.com/delta/' + folder)
    assert pipeline.run() == (0, 0)
    cfg.pull_enabled = False
    cfg.post_enabled = True
    post.reset_mock()
    assert pipeline.run() == (3, 3)
    assert post.call_args_list[0].kwargs == {}  # Normal pending mail is not range-limited.
    assert all('since' in call.kwargs for call in post.call_args_list[1:])
