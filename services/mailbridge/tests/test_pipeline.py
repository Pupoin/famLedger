from types import SimpleNamespace
from unittest.mock import Mock
import json
import logging
from datetime import datetime, timezone

import pytest
from backend.ingest import pipeline
from backend.ingest.mail_store import MailStore


def message(identifier='mail-1'):
    return {'id': identifier, 'internetMessageId': '<mail@example>', 'subject': '账户变动通知',
            'from': {'emailAddress': {'address': '95555@message.cmbchina.com'}},
            'sender': {'emailAddress': {'name': 'Bank', 'address': '95555@message.cmbchina.com'}},
            'toRecipients': [{'emailAddress': {'address': 'recipient@example.com'}}],
            'ccRecipients': [], 'bccRecipients': [],
            'receivedDateTime': datetime.now(timezone.utc).isoformat(),
            'sentDateTime': '2026-10-01T01:00:00Z',
            'body': {'contentType': 'html', 'content': '<p>Complete original body</p>'}}


def setup_pipeline(monkeypatch, tmp_path):
    cfg = SimpleNamespace(api_url='http://ledger', api_token='test-key', client_id='client', user_id='me',
                          credit_folder_name='credits', debit_folder_name='debit', database_path=tmp_path / 'mail.db',
                          tenant_id='common', graph_scopes=('Mail.Read',), token_cache_path=tmp_path / 'token.json',
                          lookback_days_credit=30, lookback_days_debit=15, replay_id="", replay_days=0,
                          pull_enabled=True, post_enabled=True)
    monkeypatch.setattr(pipeline, 'load_config', lambda: cfg)
    monkeypatch.setattr(pipeline, 'cached_account_id', lambda _: 'account-1')
    token = Mock(return_value=('graph-token', 'account-1'))
    monkeypatch.setattr(pipeline, 'acquire_graph_token', token)
    graph = Mock()
    graph.get_folder_id_by_name.side_effect = lambda name: name
    graph.delta_messages.side_effect = lambda folder, delta: ([message()] if folder == 'debit' else [], 'https://graph.microsoft.com/delta/' + folder)
    graph.get_message.side_effect = message
    monkeypatch.setattr(pipeline, 'GraphMailClient', Mock(return_value=graph))
    monkeypatch.setattr(pipeline, 'FamLedgerClient', Mock())
    post = Mock(return_value=(1, 1))
    monkeypatch.setattr(pipeline, 'sync_emails_and_parse_to_famledger', post)
    return cfg, graph, token, post


def test_complete_cache_and_incremental_poll(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    assert pipeline.run() == (1, 1)
    assert pipeline.run() == (0, 0)
    assert graph.get_message.call_count == 1
    assert graph.get_folder_id_by_name.call_count == 2
    assert post.call_count == 1
    assert graph.delta_messages.call_args.args == ('debit', 'https://graph.microsoft.com/delta/debit')
    with MailStore(cfg.database_path) as store:
        row = store.conn.execute('SELECT * FROM emails').fetchone()
        original = json.loads(row['message_json'])
        assert row['body_content'] == original['body']['content']
        assert row['from_json'] == json.dumps(original['from'], separators=(',', ':'))
        assert row['title'] == original['subject']
        assert json.loads(row['to_json']) == original['toRecipients']
        assert row['sent_at'] == original['sentDateTime']
        assert row['received_at'] == original['receivedDateTime']
        assert 'test-key' not in '\n'.join(store.conn.iterdump())


def test_pull_only_needs_no_ledger_credentials_and_leaves_mail_pending(monkeypatch, tmp_path):
    cfg, graph, _, post = setup_pipeline(monkeypatch, tmp_path)
    cfg.post_enabled = False
    cfg.api_url = cfg.api_token = ''
    client_factory = pipeline.FamLedgerClient
    assert pipeline.run() == (0, 0)
    client_factory.assert_not_called()
    post.assert_not_called()
    assert graph.get_message.call_count == 1
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        assert store.contains(source, 'mail-1')
        assert store.conn.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 0
        assert store.folder(source, 'debit')['delta_link']
    cfg.pull_enabled = False
    cfg.post_enabled = True
    cfg.api_url, cfg.api_token = 'http://ledger', 'test-key'
    graph.reset_mock()
    assert pipeline.run() == (1, 1)
    graph.get_message.assert_not_called()
    with MailStore(cfg.database_path) as store:
        assert tuple(store.conn.execute('SELECT status,attempts FROM deliveries').fetchone()) == ('sent', 1)


def test_post_only_retries_failures_without_microsoft_requests(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    post.side_effect = RuntimeError('POST failed')
    with pytest.raises(pipeline.PendingDeliveryError):
        pipeline.run()
    cfg.pull_enabled = False
    graph.reset_mock()
    token.reset_mock()
    post.side_effect = None
    assert pipeline.run() == (1, 1)
    token.assert_not_called()
    assert graph.mock_calls == []


def test_disabling_both_stages_does_not_create_cache_or_contact_either_service(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    cfg.pull_enabled = cfg.post_enabled = False
    cfg.api_url = cfg.api_token = ''
    assert pipeline.run() == (0, 0)
    assert not cfg.database_path.exists()
    token.assert_not_called()
    post.assert_not_called()
    pipeline.FamLedgerClient.assert_not_called()
    assert graph.mock_calls == []


def test_invalid_post_configuration_does_not_block_mail_caching(monkeypatch, tmp_path):
    cfg, graph, _, post = setup_pipeline(monkeypatch, tmp_path)
    cfg.api_token = ''
    from backend.ingest.famledger_sync import FamLedgerClient
    monkeypatch.setattr(pipeline, 'FamLedgerClient', FamLedgerClient)
    with pytest.raises(pipeline.PendingDeliveryError, match='POST configuration is invalid'):
        pipeline.run()
    post.assert_not_called()
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        assert store.contains(source, 'mail-1')
        assert store.conn.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 0
        assert store.folder(source, 'debit')['delta_link']


def test_failed_post_retries_from_sqlite_without_microsoft(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    post.side_effect = RuntimeError('POST failed')
    with pytest.raises(RuntimeError, match='remain pending'):
        pipeline.run()
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        assert store.folder(source, 'debit')['delta_link'] is not None
        assert store.conn.execute('SELECT status, attempts FROM deliveries').fetchone()[:] == ('failed', 1)
    token.reset_mock()
    graph.reset_mock()
    post.side_effect = None
    assert pipeline.run(fetch_new=False) == (1, 1)
    token.assert_not_called()
    graph.get_message.assert_not_called()
    with MailStore(cfg.database_path) as store:
        assert store.conn.execute('SELECT status, attempts, last_error FROM deliveries').fetchone()[:] == ('sent', 2, None)


def test_failed_delivery_logs_its_reason_and_keeps_mail_queued(monkeypatch, tmp_path, caplog):
    from backend.ingest.famledger_sync import DeliveryBlocked
    cfg, _, _, post = setup_pipeline(monkeypatch, tmp_path)
    post.side_effect = DeliveryBlocked('famLedger POST failed (HTTP 401): API Key 无效')
    with pytest.raises(pipeline.PendingDeliveryError):
        pipeline.run()
    assert 'HTTP 401' in caplog.text
    assert 'API Key 无效' in caplog.text
    with MailStore(cfg.database_path) as store:
        row = store.conn.execute('SELECT status,last_error FROM deliveries').fetchone()
        assert row['status'] == 'failed'
        assert 'HTTP 401' in row['last_error']


def test_target_change_replays_cached_mail_without_microsoft(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    pipeline.run()
    cfg.api_token = 'another-user-key'
    token.reset_mock()
    assert pipeline.run(fetch_new=False) == (1, 1)
    token.assert_not_called()
    assert graph.get_message.call_count == 1
    with MailStore(cfg.database_path) as store:
        assert store.conn.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 2


def test_mailbox_partition_and_ambiguous_cached_account(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    pipeline.run()
    monkeypatch.setattr(pipeline, 'cached_account_id', lambda _: 'account-2')
    assert pipeline.run(fetch_new=False) == (0, 0)
    assert post.call_count == 1
    monkeypatch.setattr(pipeline, 'cached_account_id', lambda _: None)
    with pytest.raises(RuntimeError, match='single cached'):
        pipeline.run(fetch_new=False)


def test_interrupted_download_keeps_previous_cursor_and_partial_cache(monkeypatch, tmp_path):
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    graph.delta_messages.side_effect = lambda folder, delta: ([message('one'), message('two')] if folder == 'debit' else [], 'https://graph.microsoft.com/delta/' + folder)
    graph.get_message.side_effect = [message('one'), RuntimeError('download failed')]
    with pytest.raises(RuntimeError, match='download failed'):
        pipeline.run()
    with MailStore(cfg.database_path) as store:
        assert store.contains(pipeline.source_key(cfg, 'account-1'), 'one')
        assert store.folder(pipeline.source_key(cfg, 'account-1'), 'debit')['delta_link'] is None
    graph.get_message.side_effect = message
    assert pipeline.run() == (2, 2)
    assert graph.get_message.call_count == 3


def test_cache_rejects_body_preview_and_deduplicates_per_mailbox(tmp_path):
    with MailStore(tmp_path / 'mail.db') as store:
        incomplete = message()
        incomplete.pop('body')
        incomplete['bodyPreview'] = 'truncated'
        with pytest.raises(ValueError, match='complete'):
            store.save_message('a', 'debit', 'debit', incomplete)
        for source in ['a', 'a', 'b']:
            store.save_message(source, 'debit', 'debit', message())
        assert store.conn.execute('SELECT count(*) FROM emails').fetchone()[0] == 2


def test_increasing_lookback_days_backfills_once(monkeypatch, tmp_path):
    from datetime import timedelta
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    pipeline.run()
    old = message('older-mail')
    old['receivedDateTime'] = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    graph.delta_messages.side_effect = lambda folder, delta: ([old] if folder == 'debit' else [], 'https://graph.microsoft.com/delta/' + folder)
    graph.get_message.side_effect = lambda identifier: old
    cfg.lookback_days_debit = 3000
    assert pipeline.run() == (1, 1)
    assert graph.delta_messages.call_args.args == ('debit', None)
    assert pipeline.run() == (0, 0)
    assert graph.delta_messages.call_args.args == ('debit', 'https://graph.microsoft.com/delta/debit')
    with MailStore(cfg.database_path) as store:
        assert store.history_days(pipeline.source_key(cfg, 'account-1'), 'debit') == 3000


@pytest.mark.parametrize('folder,field', [('credits', 'lookback_days_credit'), ('debit', 'lookback_days_debit')])
def test_shrinking_then_restoring_lookback_rescans_each_change_without_reposting(monkeypatch, tmp_path, folder, field):
    from datetime import timedelta
    cfg, graph, _, post = setup_pipeline(monkeypatch, tmp_path)
    setattr(cfg, field, 3000)
    rows = {}
    for identifier, age in [('cached-old', 90), ('new-recent', 10), ('new-old', 120)]:
        row = message(identifier)
        row['receivedDateTime'] = (datetime.now(timezone.utc) - timedelta(days=age)).isoformat()
        if folder == 'credits':
            row['subject'] = '每日信用管家'
            row['from']['emailAddress']['address'] = 'ccsvc@message.cmbchina.com'
        rows[identifier] = row
    full_scan = ['cached-old']
    graph.delta_messages.side_effect = lambda name, cursor: (
        [rows[key] for key in full_scan] if name == folder and cursor is None else [],
        'https://graph.microsoft.com/delta/' + name)
    graph.get_message.side_effect = lambda identifier: rows[identifier]
    assert pipeline.run() == (1, 1)
    full_scan[:] = ['cached-old', 'new-recent', 'new-old']
    setattr(cfg, field, 50)
    graph.delta_messages.reset_mock()
    assert pipeline.run() == (1, 1)
    assert (folder, None) in [call.args for call in graph.delta_messages.call_args_list]
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        assert store.history_days(source, folder) == 50
        assert store.contains(source, 'cached-old')  # Decreasing the window preserves prior mail.
        assert not store.contains(source, 'new-old')
    assert pipeline.run() == (0, 0)
    setattr(cfg, field, 3000)
    graph.delta_messages.reset_mock()
    assert pipeline.run() == (1, 1)
    assert (folder, None) in [call.args for call in graph.delta_messages.call_args_list]
    assert pipeline.run() == (0, 0)
    assert graph.get_message.call_count == post.call_count == 3
    with MailStore(cfg.database_path) as store:
        assert store.history_days(source, folder) == 3000
        assert [tuple(row) for row in store.conn.execute('SELECT status,attempts FROM deliveries')] == [('sent', 1)] * 3


def test_failed_changed_lookback_retries_history_before_saving_new_setting(monkeypatch, tmp_path):
    cfg, graph, _, _ = setup_pipeline(monkeypatch, tmp_path)
    assert pipeline.run() == (1, 1)
    source = pipeline.source_key(cfg, 'account-1')
    cfg.lookback_days_debit = 3000
    graph.delta_messages.side_effect = lambda name, cursor: (
        [message('new-mail')] if name == 'debit' else [], 'https://graph.microsoft.com/delta/' + name)
    graph.get_message.side_effect = RuntimeError('download interrupted')
    with pytest.raises(RuntimeError, match='download interrupted'):
        pipeline.run()
    with MailStore(cfg.database_path) as store:
        assert store.history_days(source, 'debit') == 15
    graph.delta_messages.reset_mock()
    graph.get_message.side_effect = message
    assert pipeline.run() == (1, 1)
    assert ('debit', None) in [call.args for call in graph.delta_messages.call_args_list]
    with MailStore(cfg.database_path) as store:
        assert store.history_days(source, 'debit') == 3000


def test_old_capped_scan_is_rebuilt_once_even_if_lookback_is_unchanged(monkeypatch, tmp_path):
    cfg, graph, _, post = setup_pipeline(monkeypatch, tmp_path)
    assert pipeline.run() == (1, 1)
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        store.conn.execute("DELETE FROM sync_state WHERE state_key LIKE 'scan_version:%'")
        store.conn.commit()
    graph.delta_messages.reset_mock()
    assert pipeline.run() == (0, 0)
    assert all(call.args[1] is None for call in graph.delta_messages.call_args_list)
    assert post.call_count == graph.get_message.call_count == 1
    graph.delta_messages.reset_mock()
    assert pipeline.run() == (0, 0)
    assert all(call.args[1] is not None for call in graph.delta_messages.call_args_list)


def test_scan_logs_distinguish_reading_cached_mail_from_posting(monkeypatch, tmp_path, caplog):
    cfg, _, _, _ = setup_pipeline(monkeypatch, tmp_path)
    pipeline.run()
    cfg.lookback_days_debit = 50
    caplog.set_level(logging.INFO, logger='backend.ingest.pipeline')
    assert pipeline.run() == (0, 0)
    assert 'lookback_days=50 previous_lookback_days=15 mode=history' in caplog.text
    assert 'listed=1 cached=0 already_cached=1' in caplog.text
    assert 'fetched=1, cached=0, processed=0, created=0, failed=0' in caplog.text


def test_target_outage_stops_posts_but_still_caches_new_mail(monkeypatch, tmp_path):
    from backend.ingest.famledger_sync import DeliveryBlocked
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    source = pipeline.source_key(cfg, 'account-1')
    with MailStore(cfg.database_path) as store:
        for index in range(20):
            store.save_message(source, 'debit', 'debit', message('cached-' + str(index)))
    post.side_effect = DeliveryBlocked('Target offline')
    with pytest.raises(RuntimeError, match='remain pending'):
        pipeline.run()
    assert post.call_count == 1
    assert graph.get_message.call_count == 1
    with MailStore(cfg.database_path) as store:
        assert store.contains(source, 'mail-1')
        assert store.conn.execute('SELECT count(*) FROM emails').fetchone()[0] == 21
        assert store.folder(source, 'debit')['delta_link'] is not None
    post.side_effect = None
    token.reset_mock()
    assert pipeline.run(fetch_new=False) == (21, 21)
    token.assert_not_called()


def test_replay_marker_resumes_pending_without_resetting_acknowledged_mail(monkeypatch, tmp_path):
    from backend.ingest.famledger_sync import DeliveryBlocked
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    graph.delta_messages.side_effect = lambda folder, delta: ([message('one'), message('two')] if folder == 'debit' else [], 'https://graph.microsoft.com/delta/' + folder)
    assert pipeline.run() == (2, 2)
    cfg.replay_id = 'restore-1'
    post.side_effect = [(1, 0), DeliveryBlocked('Target interrupted')]
    with pytest.raises(RuntimeError, match='remain pending'):
        pipeline.run(fetch_new=False)
    post.side_effect = None
    post.return_value = (1, 0)
    assert pipeline.run(fetch_new=False) == (1, 0)
    assert pipeline.run(fetch_new=False) == (0, 0)
    assert post.call_count == 5
    cfg.replay_id = 'restore-2'
    assert pipeline.run(fetch_new=False) == (2, 0)


def test_incremental_cursor_recovers_mail_older_than_initial_window(monkeypatch, tmp_path):
    from datetime import timedelta
    cfg, graph, token, post = setup_pipeline(monkeypatch, tmp_path)
    pipeline.run()
    missed = message('missed-during-outage')
    missed['receivedDateTime'] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    graph.delta_messages.side_effect = lambda folder, delta: ([missed] if folder == 'debit' else [], 'https://graph.microsoft.com/delta/' + folder)
    graph.get_message.side_effect = lambda identifier: missed
    assert pipeline.run() == (1, 1)
    assert graph.delta_messages.call_args.args == ('debit', 'https://graph.microsoft.com/delta/debit')
