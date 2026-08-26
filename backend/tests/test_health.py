"""Tests for GET /api/health.

The endpoint exists for two jobs: telling a container health check whether this
process can still serve, and telling a human which version is actually running
after a deploy.
"""

from version import __version__
from services.schema import SCHEMA_VERSION


def test_health_is_reachable_without_authentication(client):
    """A health check that needs a session cookie is useless to Docker."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_reports_version_and_schema_version(client):
    """Without this, "did my upgrade actually take effect?" is unanswerable from
    outside the container."""
    body = client.get("/api/health").json()

    assert body["version"] == __version__
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["database"] == "ok"


def test_health_returns_503_when_the_database_is_unreachable(client, monkeypatch):
    """The failure worth catching is a process that still holds the port while
    being unable to serve. `restart: unless-stopped` cannot see that, because it
    reacts to the process exiting rather than to it wedging — so the health check
    has to actually touch the database.
    """
    import main

    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("database is gone")

    monkeypatch.setattr(main, "engine", _BrokenEngine())

    resp = client.get("/api/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    # Version is still reported, so a probe can distinguish "wrong version" from
    # "unreachable".
    assert body["version"] == __version__
