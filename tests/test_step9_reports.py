def create_report_fixture(client):
    registration = client.post(
        "/auth/register-business",
        json={
            "business_name": "Report Shop",
            "owner_name": "Report Owner",
            "email": "report.owner@example.com",
            "password": "StrongPass!123",
        },
    )
    assert registration.status_code == 200, registration.text
    owner_headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    locations = []
    for name in ("Main", "Annex"):
        response = client.post(
            "/locations",
            json={"name": name},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        locations.append(response.json())

    product_response = client.post(
        "/products",
        json={"name": "Widget", "selling_price": "200"},
        headers=owner_headers,
    )
    assert product_response.status_code == 200, product_response.text
    product = product_response.json()

    for location in locations:
        period_response = client.post(
            f"/locations/{location['id']}/periods",
            json={"start_date": "2026-10-01"},
            headers=owner_headers,
        )
        assert period_response.status_code == 201, period_response.text
        period = period_response.json()
        entry_response = client.post(
            f"/periods/{period['id']}/stock-entries",
            json={
                "product_id": product["id"],
                "quantity": "20",
                "buying_price": "130",
                "entry_date": "2026-10-10",
            },
            headers=owner_headers,
        )
        assert entry_response.status_code == 201, entry_response.text

        count_response = client.put(
            f"/periods/{period['id']}/counts/{product['id']}",
            json={"unsold_qty": "5", "lost_damaged_qty": "1"},
            headers=owner_headers,
        )
        assert count_response.status_code == 200, count_response.text

        close_response = client.post(
            f"/periods/{period['id']}/close",
            headers=owner_headers,
        )
        assert close_response.status_code == 200, close_response.text

    return owner_headers, locations, product, registration.json()


def test_summary_report_aggregates_closed_periods_and_filters(client):
    owner_headers, locations, product, registration = create_report_fixture(client)
    query = "date_from=2026-10-01&date_to=2026-10-31"
    response = client.get(f"/reports/summary?{query}", headers=owner_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["totals"] == {
        "sold": "28.000",
        "revenue": "5600.00",
        "cost_of_sold": "3640.00",
        "profit": "1960.00",
    }
    assert payload["products"] == [
        {
            "product_id": product["id"],
            "product_name": "Widget",
            "sold": "28.000",
            "revenue": "5600.00",
            "cost_of_sold": "3640.00",
            "profit": "1960.00",
        }
    ]
    assert [item["location_id"] for item in payload["locations"]] == [
        locations[0]["id"],
        locations[1]["id"],
    ]

    location_filter = client.get(
        f"/reports/summary?{query}&location_id={locations[0]['id']}&product_id={product['id']}",
        headers=owner_headers,
    )
    assert location_filter.status_code == 200, location_filter.text
    assert location_filter.json()["totals"]["sold"] == "14.000"
    assert len(location_filter.json()["products"]) == 1
    assert len(location_filter.json()["locations"]) == 1

    outside_date_range = client.get(
        "/reports/summary?date_from=2026-11-01&date_to=2026-11-30",
        headers=owner_headers,
    )
    assert outside_date_range.status_code == 200, outside_date_range.text
    assert outside_date_range.json()["totals"]["sold"] == "0"
    assert outside_date_range.json()["products"] == []


def test_summary_report_limits_restricted_user_to_assigned_location(client):
    owner_headers, locations, _, registration = create_report_fixture(client)
    staff_response = client.post(
        "/staff",
        json={
            "email": "report.manager@example.com",
            "full_name": "Report Manager",
            "role": "manager",
            "location_ids": [locations[0]["id"]],
            "password": "ManagerPass!123",
        },
        headers=owner_headers,
    )
    assert staff_response.status_code == 200, staff_response.text

    login_response = client.post(
        "/auth/login",
        json={
            "email": "report.manager@example.com",
            "password": "ManagerPass!123",
            "business_id": registration["business_id"],
        },
    )
    assert login_response.status_code == 200, login_response.text
    manager_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    response = client.get(
        "/reports/summary?date_from=2026-10-01&date_to=2026-10-31",
        headers=manager_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["totals"]["sold"] == "14.000"
    assert [item["location_id"] for item in payload["locations"]] == [
        locations[0]["id"]
    ]

    denied_location = client.get(
        "/reports/summary?date_from=2026-10-01&date_to=2026-10-31"
        f"&location_id={locations[1]['id']}",
        headers=manager_headers,
    )
    assert denied_location.status_code == 404
