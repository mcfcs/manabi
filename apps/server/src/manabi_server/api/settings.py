"""App settings (single row): semester window, Google ICS feed, reminders."""

from datetime import date, datetime

from fastapi import APIRouter, Depends
from manabi_core.models import AppSettings, GcalEvent
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.db import get_db
from manabi_server.security import require_csrf

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsOut(BaseModel):
    semester_start: date
    semester_end: date
    gcal_configured: bool
    gcal_env_feeds: int  # feeds configured via GCAL_ICS_URLS in .env
    gcal_url_tail: str | None  # last chars only — the URL is a secret
    gcal_last_synced_at: datetime | None
    gcal_last_error: str | None
    class_reminders: bool
    push_configured: bool  # VAPID keys present in .env
    canvas_last_synced_at: datetime | None
    canvas_last_error: str | None
    chat_autovoice: bool
    general_chat_model: str | None  # Ollama model for the general assistant


class SettingsPatch(BaseModel):
    semester_start: date | None = None
    semester_end: date | None = None
    gcal_ics_url: str | None = None  # "" clears the feed
    class_reminders: bool | None = None
    chat_autovoice: bool | None = None
    general_chat_model: str | None = None  # "" clears (→ default model)


async def get_app_settings(db: AsyncSession) -> AppSettings:
    row = await db.get(AppSettings, 1)
    assert row is not None  # seeded by migration 0011
    return row


def _out(row: AppSettings) -> SettingsOut:
    env = get_settings()
    env_feeds = len([u for u in env.gcal_ics_urls.split(",") if u.strip()])
    return SettingsOut(
        semester_start=row.semester_start,
        semester_end=row.semester_end,
        gcal_configured=bool(row.gcal_ics_url) or env_feeds > 0,
        gcal_env_feeds=env_feeds,
        gcal_url_tail=f"…{row.gcal_ics_url[-18:]}" if row.gcal_ics_url else None,
        gcal_last_synced_at=row.gcal_last_synced_at,
        gcal_last_error=row.gcal_last_error,
        class_reminders=row.class_reminders,
        push_configured=bool(env.vapid_public_key and env.vapid_private_key),
        canvas_last_synced_at=row.canvas_last_synced_at,
        canvas_last_error=row.canvas_last_error,
        chat_autovoice=row.chat_autovoice,
        general_chat_model=row.general_chat_model,
    )


@router.get("")
async def read_settings(db: AsyncSession = Depends(get_db)) -> SettingsOut:
    return _out(await get_app_settings(db))


@router.patch("", dependencies=[Depends(require_csrf)])
async def patch_settings(
    data: SettingsPatch, db: AsyncSession = Depends(get_db)
) -> SettingsOut:
    row = await get_app_settings(db)
    if data.semester_start is not None:
        row.semester_start = data.semester_start
    if data.semester_end is not None:
        row.semester_end = data.semester_end
    if data.class_reminders is not None:
        row.class_reminders = data.class_reminders
    if data.chat_autovoice is not None:
        row.chat_autovoice = data.chat_autovoice
    if data.general_chat_model is not None:
        row.general_chat_model = data.general_chat_model.strip() or None
    if data.gcal_ics_url is not None:
        url = data.gcal_ics_url.strip()
        row.gcal_ics_url = url or None
        row.gcal_last_synced_at = None
        row.gcal_last_error = None
        if not url:
            await db.execute(delete(GcalEvent))
    await db.commit()
    return _out(row)
