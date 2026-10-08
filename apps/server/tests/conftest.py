import pytest
from manabi_server.config import get_settings


@pytest.fixture
def canvas_configured(monkeypatch):
    """Fake Canvas credentials. Tests must not depend on the owner's real
    .env (pytest runs from apps/server, where it isn't found, so three tests
    failed as "Canvas is not configured")."""
    settings = get_settings()
    monkeypatch.setattr(settings, "canvas_base_url", "https://canvas.example.edu")
    monkeypatch.setattr(settings, "canvas_access_token", "test-token")
    return settings
