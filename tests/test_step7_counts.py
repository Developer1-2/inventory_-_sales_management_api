from sqlalchemy import text


def create_count_fixture(client, email="counts.owner@example.com"):
    registration = client.post(
        "/auth/register-business",
        json={
            "business_name": "Count Shop",
            "owner_name": "Count Owner",
            "email": email,
            "password": "StrongPass!123",
        },
    )
    assert registration.status_code == 200, registration.text
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    location = client.post(
        "/locations",
        json={"name": "Main"},
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
        json={"name": "Rice", "selling_price": 200},
        headers=headers,
    )
    assert product.status_code == 200, product.text

    stock_entry = client.post(
        f"/periods/{period.json()['id']}/stock-entries",
        json={
            "product_id": product.json()["id"],
            "quantity": "20",
            "buying_price": "130",
            "entry_date": "2026-10-10",
        },
        headers=headers,
    )
    assert stock_entry.status_code == 201, stock_entry.text
    return registration.json(), period.json(), product.json(), headers


def test_get_counts_returns_live_calculations_and_single_update(client):
    owner, period, product, headers = create_count_fixture(client)
    initial = client.get(
        f"/periods/{period['id']}/counts",
        headers=headers,
    )
    assert initial.status_code == 200, initial.text
    row = initial.json()[0]
    assert row["product_id"] == product["id"]
    assert row["available"] == "20.000"
    assert row["sold"] is None
    assert row["unit_cost"] == "130.00"

    updated = client.put(
        f"/periods/{period['id']}/counts/{product['id']}",
        json={
            "unsold_qty": "5",
            "lost_damaged_qty": "1",
            "selling_price": "200",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    result = updated.json()
    assert result["sold"] == "14.000"
    assert result["revenue"] == "2800.00"
    assert result["cost_of_sold"] == "1820.00"
    assert result["profit"] == "980.00"
    assert result["recorded_by"] == owner["user_id"]


def test_bulk_count_update_is_atomic_and_rejects_invalid_unsold(client):
    _, period, product, headers = create_count_fixture(client, "bulk.owner@example.com")
    other_product = client.post(
        "/products",
        json={"name": "Beans", "selling_price": "300"},
        headers=headers,
    )
    assert other_product.status_code == 200, other_product.text

    valid_entry = client.post(
        f"/periods/{period['id']}/stock-entries",
        json={
            "product_id": other_product.json()["id"],
            "quantity": "10",
            "buying_price": "150",
            "entry_date": "2026-10-10",
        },
        headers=headers,
    )
    assert valid_entry.status_code == 201, valid_entry.text

    invalid_bulk = client.put(
        f"/periods/{period['id']}/counts",
        json=[
            {"product_id": product["id"], "unsold_qty": "10"},
            {"product_id": other_product.json()["id"], "unsold_qty": "11"},
        ],
        headers=headers,
    )
    assert invalid_bulk.status_code == 422, invalid_bulk.text

    rows = client.get(f"/periods/{period['id']}/counts", headers=headers).json()
    assert all(row["unsold_qty"] is None for row in rows)

    successful_bulk = client.put(
        f"/periods/{period['id']}/counts",
        json=[
            {"product_id": product["id"], "unsold_qty": "10"},
            {"product_id": other_product.json()["id"], "unsold_qty": "5"},
        ],
        headers=headers,
    )
    assert successful_bulk.status_code == 200, successful_bulk.text
    assert len(successful_bulk.json()) == 2


def test_count_update_rejects_closed_period(client, mysql_engine):
    _, period, product, headers = create_count_fixture(client, "closed.counts@example.com")
    with mysql_engine.begin() as conn:
        conn.execute(
            text("UPDATE periods SET status = 'closed' WHERE id = :period_id"),
            {"period_id": period["id"]},
        )

    response = client.put(
        f"/periods/{period['id']}/counts/{product['id']}",
        json={"unsold_qty": "1"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "period_closed"
