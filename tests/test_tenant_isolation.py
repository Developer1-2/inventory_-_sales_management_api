def register_business(client, name, owner, email):
    response = client.post(
        "/auth/register-business",
        json={
            "business_name": name,
            "owner_name": owner,
            "email": email,
            "password": "StrongPass!123",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {"Authorization": f"Bearer {body['access_token']}"}


def create_tenant_records(client, headers, business_name):
    location_response = client.post(
        "/locations",
        json={"name": f"{business_name} Main"},
        headers=headers,
    )
    assert location_response.status_code == 200, location_response.text
    location = location_response.json()

    product_response = client.post(
        "/products",
        json={"name": f"{business_name} Product", "selling_price": "100"},
        headers=headers,
    )
    assert product_response.status_code == 200, product_response.text
    product = product_response.json()

    period_response = client.post(
        f"/locations/{location['id']}/periods",
        json={"start_date": "2026-10-01"},
        headers=headers,
    )
    assert period_response.status_code == 201, period_response.text
    period = period_response.json()

    entry_response = client.post(
        f"/periods/{period['id']}/stock-entries",
        json={
            "product_id": product["id"],
            "quantity": "10",
            "buying_price": "50",
            "entry_date": "2026-10-10",
        },
        headers=headers,
    )
    assert entry_response.status_code == 201, entry_response.text

    return location, product, period, entry_response.json()


def test_business_cannot_read_or_modify_another_business_resources(client):
    _, headers_a = register_business(
        client,
        "Tenant A",
        "Owner A",
        "tenant-a.owner@example.com",
    )
    business_b, headers_b = register_business(
        client,
        "Tenant B",
        "Owner B",
        "tenant-b.owner@example.com",
    )
    _, _, period_a, _ = create_tenant_records(
        client,
        headers_a,
        "Tenant A",
    )
    location_b, product_b, period_b, entry_b = create_tenant_records(
        client,
        headers_b,
        "Tenant B",
    )
    staff_response = client.post(
        "/staff",
        json={
            "email": "tenant-b.staff@example.com",
            "full_name": "Tenant B Staff",
            "role": "manager",
            "location_ids": [location_b["id"]],
        },
        headers=headers_b,
    )
    assert staff_response.status_code == 200, staff_response.text
    membership_b = staff_response.json()["membership_id"]
    count_response = client.put(
        f"/periods/{period_b['id']}/counts/{product_b['id']}",
        json={"unsold_qty": "2"},
        headers=headers_b,
    )
    assert count_response.status_code == 200, count_response.text
    close_response = client.post(
        f"/periods/{period_b['id']}/close",
        headers=headers_b,
    )
    assert close_response.status_code == 200, close_response.text

    assert client.get(f"/locations/{location_b['id']}", headers=headers_a).status_code == 404
    assert all(
        location["id"] != location_b["id"]
        for location in client.get("/locations", headers=headers_a).json()
    )
    assert client.patch(
        f"/locations/{location_b['id']}",
        json={"name": "Hijacked Location"},
        headers=headers_a,
    ).status_code == 404
    assert client.get(f"/locations/{location_b['id']}/periods", headers=headers_a).status_code == 404
    assert client.post(
        f"/locations/{location_b['id']}/periods",
        json={"start_date": "2026-11-01"},
        headers=headers_a,
    ).status_code == 404

    assert client.get(f"/products/{product_b['id']}", headers=headers_a).status_code == 404
    assert client.patch(
        f"/products/{product_b['id']}",
        json={"name": "Hijacked Product"},
        headers=headers_a,
    ).status_code == 404
    assert all(
        item["id"] != product_b["id"]
        for item in client.get("/products", headers=headers_a).json()
    )
    assert client.post(
        f"/periods/{period_a['id']}/stock-entries",
        json={
            "product_id": product_b["id"],
            "quantity": "1",
            "buying_price": "1",
            "entry_date": "2026-10-10",
        },
        headers=headers_a,
    ).status_code == 404

    assert client.get(f"/periods/{period_b['id']}", headers=headers_a).status_code == 404
    assert client.get(
        f"/periods/{period_b['id']}/counts",
        headers=headers_a,
    ).status_code == 404
    assert client.put(
        f"/periods/{period_a['id']}/counts/{product_b['id']}",
        json={"unsold_qty": "1"},
        headers=headers_a,
    ).status_code == 404
    assert client.put(
        f"/periods/{period_a['id']}/counts",
        json=[{"product_id": product_b["id"], "unsold_qty": "1"}],
        headers=headers_a,
    ).status_code == 404
    assert client.post(
        f"/periods/{period_b['id']}/close",
        headers=headers_a,
    ).status_code == 404

    assert client.get(
        f"/periods/{period_b['id']}/stock-entries",
        headers=headers_a,
    ).status_code == 404
    assert client.delete(
        f"/stock-entries/{entry_b['id']}",
        headers=headers_a,
    ).status_code == 404

    cross_tenant_stock = client.post(
        f"/periods/{period_b['id']}/stock-entries",
        json={
            "product_id": product_b["id"],
            "quantity": "1",
            "buying_price": "1",
            "entry_date": "2026-10-10",
        },
        headers=headers_a,
    )
    assert cross_tenant_stock.status_code == 404

    report_query = "date_from=2026-10-01&date_to=2026-10-31"
    assert client.get(
        f"/reports/summary?{report_query}&location_id={location_b['id']}",
        headers=headers_a,
    ).status_code == 404
    assert client.get(
        f"/reports/summary?{report_query}&product_id={product_b['id']}",
        headers=headers_a,
    ).status_code == 404
    own_report = client.get(
        f"/reports/summary?{report_query}",
        headers=headers_a,
    )
    assert own_report.status_code == 200, own_report.text
    assert own_report.json()["totals"]["sold"] == "0"
    assert own_report.json()["locations"] == []
    assert all(
        member["membership_id"] != membership_b
        for member in client.get("/staff", headers=headers_a).json()
    )
    assert client.patch(
        f"/staff/{membership_b}",
        json={"role": "salesperson"},
        headers=headers_a,
    ).status_code == 404
    assert client.post(
        "/auth/login",
        json={
            "email": "tenant-a.owner@example.com",
            "password": "StrongPass!123",
            "business_id": business_b["business_id"],
        },
    ).status_code == 404


def test_openapi_documents_routes_with_tags_and_response_schemas():
    from app.main import app

    paths = app.openapi()["paths"]
    for path, path_item in paths.items():
        if path == "/debug-error":
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert operation.get("tags"), f"{method.upper()} {path} has no tags"
            if "requestBody" in operation:
                assert any(
                    media_type.get("schema")
                    for media_type in operation["requestBody"]["content"].values()
                ), f"{method.upper()} {path} has no request schema"
            success_responses = [
                response
                for status, response in operation["responses"].items()
                if status.startswith("2")
            ]
            assert success_responses, f"{method.upper()} {path} has no success response"
            for response in success_responses:
                if response.get("content"):
                    assert any(
                        media_type.get("schema")
                        for media_type in response["content"].values()
                    ), f"{method.upper()} {path} has an undocumented response body"


def test_auth_login_is_rate_limited(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.db import get_conn
    from app.core.limiting import limiter
    from app.main import app

    class EmptyResult:
        def fetchall(self):
            return []

    class EmptyConnection:
        def execute(self, *_args, **_kwargs):
            return EmptyResult()

    monkeypatch.setitem(app.dependency_overrides, get_conn, lambda: EmptyConnection())
    limiter.reset()
    try:
        with TestClient(app) as client:
            for _ in range(10):
                response = client.post(
                    "/auth/login",
                    json={
                        "email": "unknown@example.com",
                        "password": "not-a-password",
                    },
                )
                assert response.status_code == 401

            limited = client.post(
                "/auth/login",
                json={
                    "email": "unknown@example.com",
                    "password": "not-a-password",
                },
            )
            assert limited.status_code == 429
    finally:
        limiter.reset()
