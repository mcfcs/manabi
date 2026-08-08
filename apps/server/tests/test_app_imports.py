def test_app_assembles():
    from manabi_server.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/health" in paths
    assert "/api/auth/login" in paths
    assert "/api/jobs/echo" in paths
