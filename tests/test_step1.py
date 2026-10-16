from fastapi.testclient import TestClient

from app.core.errors import AppError
from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_error_format():
    def raise_error():
        raise AppError(400, "bad_request", "invalid payload")

    app.add_api_route("/debug-error", raise_error, methods=["GET"])
    with TestClient(app) as client:
        response = client.get("/debug-error")
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "bad_request", "message": "invalid payload"}}
