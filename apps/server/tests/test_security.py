from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from manabi_server.security import require_csrf


def _csrf_app() -> TestClient:
    app = FastAPI()

    @app.post("/mutate", dependencies=[Depends(require_csrf)])
    def mutate() -> dict:
        return {"ok": True}

    @app.get("/read", dependencies=[Depends(require_csrf)])
    def read() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_csrf_blocks_mutation_without_header():
    client = _csrf_app()
    assert client.post("/mutate").status_code == 403


def test_csrf_allows_mutation_with_header():
    client = _csrf_app()
    r = client.post("/mutate", headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200


def test_csrf_allows_same_origin_any_host():
    """Same-origin requests pass for any tailnet hostname/IP."""
    client = _csrf_app()
    r = client.post(
        "/mutate",
        headers={
            "X-Requested-With": "fetch",
            "Origin": "http://phillmyeol:56690",
            "Host": "phillmyeol:56690",
        },
    )
    assert r.status_code == 200


def test_csrf_rejects_foreign_origin():
    client = _csrf_app()
    r = client.post(
        "/mutate",
        headers={"X-Requested-With": "fetch", "Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_csrf_ignores_get():
    client = _csrf_app()
    assert client.get("/read").status_code == 200
