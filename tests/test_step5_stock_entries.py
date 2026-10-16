from sqlalchemy import text


def create_owner_and_period(client, email="stock.owner@example.com"):
    registered = client.post(
        "/auth/register-business",
        json={
            "business_name": "Stock Shop",
            "owner_name": "Stock Owner",
            "email": email,
            "password": "StrongPass!123",
        },
    )
    assert registered.status_code == 200, registered.text
    owner = registered.json()
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}

    location_response = client.post(
        "/locations",
        json={"name": "Main", "address": "Kampala"},
        headers=owner_headers,
    )
    assert location_response.status_code == 200, location_response.text
    location = location_response.json()

    period_response = client.post(
        f"/locations/{location['id']}/periods",
        json={"start_date": "2026-10-01"},
        headers=owner_headers,
    )
    assert period_response.status_code == 201, period_response.text
    return owner, location, period_response.json(), owner_headers


def test_create_list_filter_and_delete_stock_entry(client):
    _, _, period, headers = create_owner_and_period(client)
    product_response = client.post(
        "/products",
        json={"name": "Coffee", "selling_price": 3000},
        headers=headers,
    )
    assert product_response.status_code == 200, product_response.text
    product_id = product_response.json()["id"]

    created = client.post(
        f"/periods/{period['id']}/stock-entries",
        json={
            "product_id": product_id,
            "quantity": "12.500",
            "buying_price": "1800.25",
            "entry_date": "2026-10-16",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["quantity"] == "12.500"
    assert entry["buying_price"] == "1800.25"

    listing = client.get(
        f"/periods/{period['id']}/stock-entries?product_id={product_id}",
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    assert [row["id"] for row in listing.json()] == [entry["id"]]

    detail = client.get(f"/periods/{period['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["counts"][0]["product_id"] == product_id

    deleted = client.delete(f"/stock-entries/{entry['id']}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert client.get(
        f"/periods/{period['id']}/stock-entries",
        headers=headers,
    ).json() == []


def test_stock_entry_validation_and_closed_period_rejection(client, mysql_engine):
    owner, _, period, headers = create_owner_and_period(client)
    product = client.post(
        "/products",
        json={"name": "Sugar", "selling_price": 5000},
        headers=headers,
    )
    assert product.status_code == 200, product.text
    payload = {
        "product_id": product.json()["id"],
        "quantity": "1",
        "buying_price": "4000",
        "entry_date": "2026-10-16",
    }

    outside_period = client.post(
        f"/periods/{period['id']}/stock-entries",
        json={**payload, "entry_date": "2026-11-01"},
        headers=headers,
    )
    assert outside_period.status_code == 422

    with mysql_engine.begin() as conn:
        conn.execute(
            text("UPDATE periods SET status = 'closed' WHERE id = :period_id"),
            {"period_id": period["id"]},
        )
    closed = client.post(
        f"/periods/{period['id']}/stock-entries",
        json=payload,
        headers=headers,
    )
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "period_closed"


def test_salesperson_can_only_add_entries_at_assigned_location(client):
    _, _, period, owner_headers = create_owner_and_period(client)
    location_id = period["location_id"]
    product = client.post(
        "/products",
        json={"name": "Tea", "selling_price": 1000},
        headers=owner_headers,
    )
    assert product.status_code == 200, product.text

    staff = client.post(
        "/staff",
        json={
            "email": "salesperson.stock@example.com",
            "full_name": "Sally Sales",
            "role": "salesperson",
            "location_ids": [location_id],
        },
        headers=owner_headers,
    )
    assert staff.status_code == 200, staff.text

    login = client.post(
        "/auth/login",
        json={"email": "salesperson.stock@example.com", "password": "Welcome123!"},
    )
    assert login.status_code == 200, login.text
    salesperson_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = client.post(
        f"/periods/{period['id']}/stock-entries",
        json={
            "product_id": product.json()["id"],
            "quantity": "2",
            "buying_price": "700",
            "entry_date": "2026-10-05",
        },
        headers=salesperson_headers,
    )
    assert created.status_code == 201, created.text

    other_owner, other_location, other_period, _ = create_owner_and_period(
        client, "different.stock.owner@example.com"
    )
    assert other_owner["business_id"] != period["business_id"]
    denied = client.post(
        f"/periods/{other_period['id']}/stock-entries",
        json={
            "product_id": product.json()["id"],
            "quantity": "2",
            "buying_price": "700",
            "entry_date": "2026-10-05",
        },
        headers=salesperson_headers,
    )
    assert denied.status_code == 404
