from fastapi.testclient import TestClient

from app.main import app


def test_client_routes_fall_back_to_frontend() -> None:
    client = TestClient(app)
    for path in ("/login", "/", "/dashboard", "/players", "/audit-log"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert '<div id="root"></div>' in response.text


def test_missing_assets_and_api_routes_remain_not_found() -> None:
    client = TestClient(app)
    assert client.get("/assets/missing.js").status_code == 404

    api_response = client.get("/api/not-a-route")
    assert api_response.status_code == 404
    assert api_response.headers["content-type"].startswith("application/json")
