from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from manabi_server.security import hash_password, require_csrf, verify_password


def test_password_hash_roundtrip():
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "wrong password")


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
