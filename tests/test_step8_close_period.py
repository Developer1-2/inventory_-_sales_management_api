from sqlalchemy import text


def create_period_fixture(client, email="close.owner@example.com"):
    registration = client.post(
        "/auth/register-business",
        json={
            "business_name": "Close Shop",
            "owner_name": "Close Owner",
            "email": email,
            "password": "StrongPass!123",
        },
    )
    assert registration.status_code == 200, registration.text
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    location = client.post(
        "/locations",
        json={"name": "Main", "address": "Kampala"},
        headers=headers,
    )
    assert location.status_code == 200, location.text

    period = client.post(
        f"/locations/{location.json()['id']}/periods",
        json={"start_date": "2026-10-01"},
        headers=headers,
    )
    assert period.status_code == 201, period.text

    product = client.post(
        "/products",
        json={"name": "Widget", "selling_price": "200"},
        headers=headers,
    )
    assert product.status_code == 200, product.text
    return registration.json(), location.json(), period.json(), product.json(), headers


def test_close_period_success_and_carry_over(client, mysql_engine):
    _, location, period, product, headers = create_period_fixture(client)
    with mysql_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stock_entries (business_id, location_id, period_id, product_id, quantity, buying_price, entry_date, recorded_by) "
                "VALUES (:business_id, :location_id, :period_id, :product_id, :quantity, :buying_price, :entry_date, :recorded_by)"
            ),
            {
                "business_id": 1,
                "location_id": location["id"],
                "period_id": period["id"],
                "product_id": product["id"],
                "quantity": "20",
                "buying_price": "130",
                "entry_date": "2026-10-15",
                "recorded_by": 1,
            },
        )
        conn.execute(
            text(
                "UPDATE period_counts SET opening_qty = :opening_qty, opening_unit_cost = :opening_unit_cost, "
                "unsold_qty = :unsold_qty, lost_damaged_qty = :lost_damaged_qty, selling_price = :selling_price, recorded_by = :recorded_by "
                "WHERE period_id = :period_id AND product_id = :product_id"
            ),
            {
                "opening_qty": "10",
                "opening_unit_cost": "100",
                "unsold_qty": "5",
                "lost_damaged_qty": "1",
                "selling_price": "200",
                "recorded_by": 1,
                "period_id": period["id"],
                "product_id": product["id"],
            },
        )

    response = client.post(f"/periods/{period['id']}/close", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["closed_period_id"] == period["id"]
    assert payload["new_period_id"] > period["id"]
    assert payload["summary"][0]["product_id"] == product["id"]
    assert payload["summary"][0]["sold"] == "24"
    assert payload["summary"][0]["profit"] == "1920.00"

    with mysql_engine.begin() as conn:
        next_count = conn.execute(
            text(
                "SELECT opening_qty, opening_unit_cost, selling_price FROM period_counts "
                "WHERE period_id = :period_id AND product_id = :product_id"
            ),
            {"period_id": payload["new_period_id"], "product_id": product["id"]},
        ).fetchone()
        assert next_count is not None
        assert str(next_count[0]) == "5"
        assert str(next_count[1]) == "120.00"
        assert str(next_count[2]) == "200.00"


def test_close_period_rejects_missing_counts(client):
    _, _, period, product, headers = create_period_fixture(client, "missing.owner@example.com")
    with client as test_client:
        response = test_client.post(f"/periods/{period['id']}/close", headers=headers)
    assert response.status_code == 422, response.text
    assert "Missing unsold quantity" in response.json()["error"]["message"]


def test_close_period_rejects_already_closed(client, mysql_engine):
    _, _, period, product, headers = create_period_fixture(client, "closed.owner@example.com")
    with mysql_engine.begin() as conn:
        conn.execute(
            text("UPDATE periods SET status = 'closed' WHERE id = :period_id"),
            {"period_id": period["id"]},
        )
    response = client.post(f"/periods/{period['id']}/close", headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "period_already_closed"
