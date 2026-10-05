from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from backend import worker


@pytest.mark.parametrize('child_exit,expected', [(0, 0), (1, 1)])
def test_single_run_reports_child_result(monkeypatch, child_exit, expected):
    monkeypatch.setattr(worker, 'load_config', lambda: SimpleNamespace(pull_enabled=True, post_enabled=True, task_timeout=30))
    process = Mock(exitcode=child_exit)
    process.is_alive.return_value = False
    factory = Mock(return_value=process)
    monkeypatch.setattr(worker.multiprocessing, 'Process', factory)
    assert worker.run_once(fetch_new=False) == expected
    assert factory.call_args.kwargs['args'] == (False,)


def test_timeout_terminates_and_reports_failure(monkeypatch):
    monkeypatch.setattr(worker, 'load_config', lambda: SimpleNamespace(pull_enabled=True, post_enabled=True, task_timeout=30))
    process = Mock()
    process.is_alive.side_effect = [True, False]
    monkeypatch.setattr(worker.multiprocessing, 'Process', Mock(return_value=process))
    assert worker.run_once() == 1
    process.terminate.assert_called_once()


@pytest.mark.parametrize('pull,post,cached_only,starts,effective_pull', [
    (True, True, False, True, True),
    (True, False, False, True, True),
    (False, True, False, True, False),
    (False, False, False, False, False),
    (True, True, True, True, False),
    (True, False, True, False, False),
])
def test_stage_switches_and_cached_only_mode(monkeypatch, pull, post, cached_only, starts, effective_pull):
    # Pull-only operation has no famLedger URL or Key configured.
    monkeypatch.setattr(worker, 'load_config', lambda: SimpleNamespace(
        pull_enabled=pull, post_enabled=post, task_timeout=30))
    process = Mock(exitcode=0)
    process.is_alive.return_value = False
    factory = Mock(return_value=process)
    monkeypatch.setattr(worker.multiprocessing, 'Process', factory)
    assert worker.run_once(fetch_new=not cached_only) == 0
    if starts:
        assert factory.call_args.kwargs['args'] == (effective_pull,)
        process.start.assert_called_once()
    else:
        factory.assert_not_called()


def test_expected_pending_delivery_exits_without_duplicate_traceback(monkeypatch, caplog):
    from backend.ingest.pipeline import PendingDeliveryError
    run = Mock(side_effect=PendingDeliveryError('1 cached emails remain pending; retry next cycle'))
    monkeypatch.setattr(worker, 'run', run)
    with pytest.raises(SystemExit) as error:
        worker._worker(False)
    assert error.value.code == 1
    assert 'remain pending' in caplog.text
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is None
    run.assert_called_once_with(fetch_new=False)


def test_unexpected_failure_is_logged_once_with_traceback(monkeypatch, caplog):
    monkeypatch.setattr(worker, 'run', Mock(side_effect=ValueError('unexpected parser failure')))
    with pytest.raises(SystemExit) as error:
        worker._worker(True)
    assert error.value.code == 1
    assert 'unexpected parser failure' in caplog.text
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is not None
