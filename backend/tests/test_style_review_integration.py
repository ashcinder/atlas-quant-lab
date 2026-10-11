from uuid import uuid4

from fastapi.testclient import TestClient

from app import style_review
from app.main import app


def test_real_auth_origin_and_style_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(style_review, "DB", tmp_path / "style.db")
    client = TestClient(app)
    url = "/api/v1/style-review/reports"
    assert client.get(url).status_code == 401
    response = client.post(
        "/api/register",
        json={
            "email": f"style-{uuid4()}@example.test",
            "password": "local-test-password-123",
        },
    )
    assert response.status_code == 201
    assert client.get(url).json() == []
    assert (
        client.post(url, json={}, headers={"Origin": "https://untrusted.invalid"}).status_code
        == 403
    )
    assert client.post(url, content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post(url, json={}).status_code == 422
    assert client.get(url + "/missing").status_code == 404
