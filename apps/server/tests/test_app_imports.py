def test_app_assembles():
    from manabi_server.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/health" in paths
    assert "/api/me" in paths
    assert "/api/jobs/echo" in paths
    # login is gone by design (single-user, tailnet-gated)
    assert "/api/auth/login" not in paths
