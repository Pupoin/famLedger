import pytest

from backend import config


@pytest.mark.parametrize('value,expected', [
    (None, ('localhost', '127.0.0.1', 'testserver')),
    (' , ', ('localhost', '127.0.0.1', 'testserver')),
    (' MAILBRIDGE.EXAMPLE.COM ,192.168.1.10,mailbridge.example.com ',
     ('localhost', '127.0.0.1', 'mailbridge.example.com', '192.168.1.10')),
    ('*.example.com', ('localhost', '127.0.0.1', '*.example.com')),
])
def test_allowed_hosts_defaults_and_custom_values(monkeypatch, value, expected):
    monkeypatch.setattr(config, 'load_dotenv', lambda *args, **kwargs: None)
    if value is None:
        monkeypatch.delenv('MAILBRIDGE_ALLOWED_HOSTS', raising=False)
    else:
        monkeypatch.setenv('MAILBRIDGE_ALLOWED_HOSTS', value)
    assert config.load_allowed_hosts() == expected


def test_allowed_hosts_loads_dotenv_without_overriding_container_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    (tmp_path / '.env').write_text('MAILBRIDGE_ALLOWED_HOSTS=dotenv.example.com\n')
    monkeypatch.setenv('MAILBRIDGE_ALLOWED_HOSTS', '')
    monkeypatch.delenv('MAILBRIDGE_ALLOWED_HOSTS', raising=False)
    assert 'dotenv.example.com' in config.load_allowed_hosts()
    monkeypatch.setenv('MAILBRIDGE_ALLOWED_HOSTS', 'container.example.com')
    assert config.load_allowed_hosts() == ('localhost', '127.0.0.1', 'container.example.com')


@pytest.mark.parametrize('value', ['https://mailbridge.example.com', 'example.com:8502',
                                 'example.com/path', 'example com', 'mail*bridge.example.com'])
def test_allowed_hosts_rejects_urls_ports_paths_and_invalid_wildcards(monkeypatch, value):
    monkeypatch.setattr(config, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setenv('MAILBRIDGE_ALLOWED_HOSTS', value)
    with pytest.raises(ValueError, match='MAILBRIDGE_ALLOWED_HOSTS'):
        config.load_allowed_hosts()


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
