from sqlalchemy import text

from app.main import app


def test_register_business(client):
    payload = {
        "business_name": "Acme Traders",
        "owner_name": "Daniel Omar",
        "email": "owner@example.com",
        "password": "StrongPass!123",
    }

    response = client.post("/auth/register-business", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "owner"
    assert data["business_id"] > 0
    assert data["user_id"] > 0


def test_login_returns_business_choice_for_multiple_businesses(client, mysql_engine):
    payload = {
        "business_name": "Northgate Stores",
        "owner_name": "Jane Nairobi",
        "email": "multi@example.com",
        "password": "StrongPass!123",
    }

    register_response = client.post("/auth/register-business", json=payload)
    assert register_response.status_code == 200, register_response.text

    with mysql_engine.begin() as conn:
        user = conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": payload["email"].lower()},
        ).fetchone()
        assert user is not None

        second_business = conn.execute(
            text("INSERT INTO businesses (name, is_active) VALUES (:name, 1)"),
            {"name": "Southgate Stores"},
        )
        second_business_id = second_business.lastrowid
        conn.execute(
            text("INSERT INTO business_settings (business_id) VALUES (:business_id)"),
            {"business_id": second_business_id},
        )
        conn.execute(
            text(
                "INSERT INTO memberships (business_id, user_id, role, is_active) "
                "VALUES (:business_id, :user_id, 'owner', 1)"
            ),
            {"business_id": second_business_id, "user_id": user[0]},
        )

    response = client.post(
        "/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "businesses" in body
    assert len(body["businesses"]) >= 2
    assert all(item["business_id"] > 0 for item in body["businesses"])
    assert all(item["business_name"] for item in body["businesses"])
