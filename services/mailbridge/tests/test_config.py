import pytest

from backend import config


@pytest.mark.parametrize('pull,post,expected', [
    (None, None, (True, False)),
    ('true', 'false', (True, False)),
    ('false', 'true', (False, True)),
    ('false', 'false', (False, False)),
    ('true', 'true', (True, True)),
    (' YES ', '1', (True, True)),
])
def test_independent_stage_settings_and_defaults(monkeypatch, pull, post, expected):
    monkeypatch.setattr(config, 'load_dotenv', lambda *args, **kwargs: None)
    for name, value in [('MAILBRIDGE_PULL_ENABLED', pull), ('MAILBRIDGE_POST_ENABLED', post)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setenv('MAILBRIDGE_REPLAY', '')
    monkeypatch.setenv('MAILBRIDGE_SYNC_INTERVAL_SECONDS', '600')
    monkeypatch.setenv('MAILBRIDGE_TASK_TIMEOUT_SECONDS', '1000')
    # The retired master switch must never override either stage.
    monkeypatch.setenv('MAILBRIDGE_SYNC_ENABLED', 'true')
    config.load_config.cache_clear()
    try:
        cfg = config.load_config()
        assert (cfg.pull_enabled, cfg.post_enabled) == expected
    finally:
        config.load_config.cache_clear()
