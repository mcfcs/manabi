"""CPU-queue task implementations (run by `python -m manabi_server.worker`).

Tasks are SYNC on purpose: document processing is heavy blocking work, and
Procrastinate runs sync tasks in a worker thread, keeping the async worker
loop responsive. DB access uses a sync engine for the same reason.
"""

import procrastinate
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from manabi_server.config import get_settings
from manabi_server.jobs.queue import PROCESS_DOCUMENT_TASK


def _conninfo() -> str:
    return get_settings().database_url_sync.replace("postgresql+psycopg", "postgresql")


app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=_conninfo()))

_session_factory: sessionmaker | None = None


def db_session() -> Session:
    global _session_factory
    if _session_factory is None:
        engine = create_engine(get_settings().database_url_sync, pool_size=2)
        _session_factory = sessionmaker(engine)
    return _session_factory()


@app.task(name=PROCESS_DOCUMENT_TASK, queue="cpu", retry=3)
def process_document(document_id: int, job_id: int | None = None) -> None:
    from manabi_server.processing.pipeline import run_pipeline

    with db_session() as db:
        run_pipeline(db, document_id, job_id)
