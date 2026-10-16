def register_business(client, business_name, owner_name, email):
    response = client.post(
        "/auth/register-business",
        json={
            "business_name": business_name,
            "owner_name": owner_name,
            "email": email,
            "password": "StrongPass!123",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_locations_and_products_are_scoped_to_business(client):
    business_a = register_business(client, "Alpha Shop", "Owner A", "owner.a@example.com")
    business_b = register_business(client, "Beta Shop", "Owner B", "owner.b@example.com")

    location_a = client.post(
        "/locations",
        json={"name": "Main Branch", "address": "Kampala"},
        headers=auth_headers(business_a["access_token"]),
    )
    assert location_a.status_code == 200, location_a.text

    location_b = client.post(
        "/locations",
        json={"name": "Second Branch", "address": "Nairobi"},
        headers=auth_headers(business_b["access_token"]),
    )
    assert location_b.status_code == 200, location_b.text

    cross_location = client.get(
        f"/locations/{location_b.json()['id']}",
        headers=auth_headers(business_a["access_token"]),
    )
    assert cross_location.status_code == 404, cross_location.text

    product_b = client.post(
        "/products",
        json={"name": "Bags", "sku": "BAG-01", "unit": "pcs", "selling_price": 2500.0},
        headers=auth_headers(business_b["access_token"]),
    )
    assert product_b.status_code == 200, product_b.text

    cross_product = client.get(
        f"/products/{product_b.json()['id']}",
        headers=auth_headers(business_a["access_token"]),
    )
    assert cross_product.status_code == 404, cross_product.text


def test_owner_can_create_and_list_staff(client):
    business = register_business(client, "Gamma Shop", "Owner G", "owner.g@example.com")
    location = client.post(
        "/locations",
        json={"name": "Head Office", "address": "Jinja"},
        headers=auth_headers(business["access_token"]),
    )
    assert location.status_code == 200, location.text

    staff_response = client.post(
        "/staff",
        json={
            "email": "manager.g@example.com",
            "full_name": "Grace Manager",
            "role": "manager",
            "location_ids": [location.json()["id"]],
        },
        headers=auth_headers(business["access_token"]),
    )
    assert staff_response.status_code == 200, staff_response.text
    member = staff_response.json()
    assert member["role"] == "manager"
    assert member["location_ids"] == [location.json()["id"]]

    list_response = client.get("/staff", headers=auth_headers(business["access_token"]))
    assert list_response.status_code == 200, list_response.text
    assert any(item["email"] == "manager.g@example.com" for item in list_response.json())
