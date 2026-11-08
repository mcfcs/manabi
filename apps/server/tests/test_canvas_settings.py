"""Canvas token pasted in Settings: it wins over .env, is checked against
Canvas before it is saved, and an expired one says when it expired."""

from datetime import date

import httpx
import pytest
from fastapi import HTTPException
from manabi_core.models import AppSettings
from manabi_server.api import canvas
from manabi_server.api import settings as settings_api

# Canvas's real 401 for the token that expired on 2026-11-06 (Manila: Nov 7, 00:00)
EXPIRED = {"errors": [{"message": "Expired access token.", "expired_at": "2026-11-06T16:00:00Z"}]}


@pytest.fixture(autouse=True)
def _no_override():
    canvas.set_token_override(None)
    yield
    canvas.set_token_override(None)


class FakeDB:
    def __init__(self, row):
        self.row = row
        self.commits = 0

    async def get(self, model, pk):
        return self.row

    async def commit(self):
        self.commits += 1


def _row(**kw):
    return AppSettings(
        id=1,
        semester_start=date(2026, 8, 5),
        semester_end=date(2026, 12, 12),
        class_reminders=False,
        chat_autovoice=False,
        narration_enabled=False,
        grades_hidden=False,
        **kw,
    )


def _canvas_answers(monkeypatch, response):
    """Route every new httpx client (check_canvas_token builds its own) to
    `response`, recording the requests."""
    seen = []
    real = httpx.AsyncClient

    def handler(request):
        seen.append(request)
        return response

    monkeypatch.setattr(
        canvas.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    return seen


def test_settings_token_wins_over_env(canvas_configured):
    assert canvas._canvas_config()[1] == "test-token"
    assert canvas.canvas_token_source() == "env"
    canvas.set_token_override("pasted-token")
    assert canvas._canvas_config()[1] == "pasted-token"
    assert canvas.canvas_token_source() == "settings"
    canvas.set_token_override("")  # cleared → back to .env
    assert canvas._canvas_config()[1] == "test-token"


def test_no_token_anywhere_points_at_settings(canvas_configured, monkeypatch):
    monkeypatch.setattr(canvas_configured, "canvas_access_token", "")
    with pytest.raises(HTTPException) as exc:
        canvas._canvas_config()
    assert exc.value.status_code == 409 and "Settings" in exc.value.detail
    assert canvas.canvas_token_source() is None


def test_expired_token_error_says_when_in_manila_time():
    r = httpx.Response(401, json=EXPIRED)
    assert canvas.CanvasAuthError(canvas._expired_at(r)).detail == (
        "Canvas token expired Nov 7, 00:00 — paste a new one in Settings"
    )
    plain = httpx.Response(401, text="Invalid access token")
    assert canvas.CanvasAuthError(canvas._expired_at(plain)).detail == (
        "Canvas rejected the token — it may have expired"
    )


async def test_a_good_token_is_saved_and_used(canvas_configured, monkeypatch):
    seen = _canvas_answers(monkeypatch, httpx.Response(200, json={"id": 1, "name": "Gio"}))
    row = _row(canvas_last_error="Canvas token expired Nov 7, 00:00")
    out = await settings_api.patch_settings(
        settings_api.SettingsPatch(canvas_access_token="  new-token-abcd \n"), db=FakeDB(row)
    )
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/api/v1/users/self")]
    assert seen[0].headers["Authorization"] == "Bearer new-token-abcd"
    assert row.canvas_access_token == "new-token-abcd" and row.canvas_last_error is None
    assert canvas._canvas_config()[1] == "new-token-abcd"
    assert out.canvas_token_source == "settings" and out.canvas_token_tail == "…abcd"


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (httpx.Response(401, json=EXPIRED), 422),
        (httpx.Response(401, text="Invalid access token"), 422),
        (httpx.Response(500, text="down"), 502),
    ],
)
async def test_a_refused_token_is_not_saved(canvas_configured, monkeypatch, response, status):
    _canvas_answers(monkeypatch, response)
    row = _row(canvas_access_token="old-token")
    db = FakeDB(row)
    with pytest.raises(HTTPException) as exc:
        await settings_api.patch_settings(
            settings_api.SettingsPatch(canvas_access_token="bad"), db=db
        )
    assert exc.value.status_code == status
    assert row.canvas_access_token == "old-token" and db.commits == 0
    assert canvas._canvas_config()[1] == "test-token"  # override untouched


async def test_clearing_the_token_falls_back_to_env(canvas_configured):
    canvas.set_token_override("pasted-token")
    row = _row(canvas_access_token="pasted-token")
    out = await settings_api.patch_settings(
        settings_api.SettingsPatch(canvas_access_token=""), db=FakeDB(row)
    )
    assert row.canvas_access_token is None
    assert out.canvas_token_source == "env" and out.canvas_token_tail is None
