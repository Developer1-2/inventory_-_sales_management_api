from datetime import date

from sqlalchemy import text

from app.routers.periods import calculate_end_date


def create_owner_and_location(client, email="cycle.owner@example.com"):
    registration = client.post(
        "/auth/register-business",
        json={
            "business_name": "Cycle Shop",
            "owner_name": "Owner Cycle",
            "email": email,
            "password": "StrongPass!123",
        },
    )
    assert registration.status_code == 200, registration.text
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    location_response = client.post(
        "/locations",
        json={"name": "Main", "address": "Kampala"},
        headers=headers,
    )
    assert location_response.status_code == 200, location_response.text
    return registration.json(), location_response.json(), headers


def test_calculate_period_end_dates():
    assert calculate_end_date(date(2026, 2, 10), "monthly") == date(2026, 2, 28)
    assert calculate_end_date(date(2026, 10, 16), "weekly") == date(2026, 10, 22)


def test_create_period_makes_counts_for_active_products(client):
    _, location, headers = create_owner_and_location(client)
    product = client.post(
        "/products",
        json={"name": "Notebook", "selling_price": 1250.50},
        headers=headers,
    )
    assert product.status_code == 200, product.text

    inactive = client.post(
        "/products",
        json={"name": "Inactive Item", "selling_price": 10, "is_active": False},
        headers=headers,
    )
    assert inactive.status_code == 200, inactive.text

    response = client.post(
        f"/locations/{location['id']}/periods",
        json={"start_date": "2026-10-16"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["end_date"] == "2026-10-31"

    detail = client.get(f"/periods/{response.json()['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    counts = detail.json()["counts"]
    assert len(counts) == 1
    assert counts[0]["product_id"] == product.json()["id"]
    assert counts[0]["opening_qty"] == "0.000"
    assert counts[0]["opening_unit_cost"] == "0.00"
    assert counts[0]["selling_price"] == "1250.50"


def test_period_conflict_listing_and_location_scope(client):
    _, location, headers = create_owner_and_location(client)
    first = client.post(
        f"/locations/{location['id']}/periods",
        json={"start_date": "2026-10-01"},
        headers=headers,
    )
    assert first.status_code == 201, first.text

    conflict = client.post(
        f"/locations/{location['id']}/periods",
        json={"start_date": "2026-10-20"},
        headers=headers,
    )
    assert conflict.status_code == 409

    periods = client.get(f"/locations/{location['id']}/periods", headers=headers)
    assert periods.status_code == 200, periods.text
    assert len(periods.json()) == 1

    other_owner, _, other_headers = create_owner_and_location(
        client, "other.owner@example.com"
    )
    inaccessible = client.get(
        f"/periods/{first.json()['id']}",
        headers=other_headers,
    )
    assert inaccessible.status_code == 404


def test_weekly_period_end_date(client, mysql_engine):
    registration, location, headers = create_owner_and_location(client)
    with mysql_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE business_settings SET period_length = 'weekly' "
                "WHERE business_id = :business_id"
            ),
            {"business_id": registration["business_id"]},
        )

    response = client.post(
        f"/locations/{location['id']}/periods",
        json={"start_date": "2026-10-16"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["end_date"] == "2026-10-22"
