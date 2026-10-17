
## Step 10: Hardening
```
Review the whole codebase against the "Multi-tenancy rules" in the project instructions. List every SQL query on a tenant table that lacks a business_id filter, and fix them. Then add tests/test_tenant_isolation.py that creates two businesses and verifies that for every endpoint, business A cannot read or modify business B's data (expect 404). Add rate limiting on /auth routes with slowapi, CORS configuration, and make sure OpenAPI docs at /docs describe every endpoint with request and response models and tags.
```
