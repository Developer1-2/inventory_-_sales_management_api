# Copilot Agent Prompts: Phase 1 (FastAPI)

## Before you start
1. Create a project folder and open it in VS Code.
2. Create and activate a virtual environment: `python -m venv .venv`, then activate it.
3. Put `copilot-instructions.md` at `.github/copilot-instructions.md`.
4. Put `inventory_schema.sql` at `db/schema.sql`.
5. Open Copilot Chat, switch to **Agent** mode.
6. Paste ONE prompt at a time. Run the app and test before moving to the next. Commit to git after each step that works.

Tip: in each prompt, attach the schema with `#file:db/schema.sql` so the agent reads it. FastAPI gives you free interactive docs at `/docs`, which is the easiest way to try each endpoint by hand.

---

## Step 0: Scaffold
```
Using #file:db/schema.sql and the project instructions, scaffold the FastAPI project:
- folders: app/{core,routers,schemas,services,repositories}, tests/
- requirements.txt with: fastapi, uvicorn[standard], sqlalchemy, pymysql, cryptography, pydantic-settings, pyjwt, bcrypt, python-dotenv, slowapi, pytest, httpx
- .env.example (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, TEST_DB_NAME, JWT_SECRET, JWT_EXPIRES_MINUTES)
- app/core/config.py using pydantic-settings
- app/main.py with the FastAPI app and GET /health returning {"status": "ok"}
- a README with the commands to install and run: uvicorn app.main:app --reload
Do not write any other features yet.
```

## Step 1: Database layer, errors, test setup
```
Create:
1. app/core/db.py: a SQLAlchemy Core engine for MySQL (pymysql, pool_pre_ping=True), a get_conn FastAPI dependency, and a transaction() context manager that wraps engine.begin(). DECIMAL columns must come back as Python Decimal.
2. app/core/errors.py: an AppError(status_code, code, message) class and exception handlers registered in main.py. Handle AppError and RequestValidationError, all returning {"error": {"code", "message"}}.
3. tests/conftest.py: a pytest fixture that connects to the TEST_DB_NAME database, creates the tables from db/schema.sql once per session, truncates all tables between tests, and provides a TestClient whose get_conn dependency is overridden to use the test database.
Add one test for the error format and one for /health.
```

## Step 2: Auth
```
Implement authentication:
- app/core/security.py: hash_password / verify_password with bcrypt, create_access_token / decode_token with PyJWT.
- POST /auth/register-business: body { business_name, owner_name, email, password }. In one transaction create: business, business_settings (defaults), user, membership with role 'owner'. Return a JWT.
- POST /auth/login: body { email, password, business_id? }. If the user belongs to several businesses and business_id is missing, return the list so the client can choose. JWT payload: user_id, business_id, role, membership_id.
- app/deps.py: get_auth dependency that verifies the JWT and returns an AuthContext (user_id, business_id, role, membership_id, location_ids; owners get "all"). Also require_role("owner", "manager") and a dependency that checks location access for a location_id path parameter, returning 404 if not allowed.
Use Pydantic models for input and output. Add pytest tests for register and login.
```

## Step 3: Locations, products, staff
```
Implement, following the tenant rules in the instructions:
- Locations: POST/GET/PATCH /locations (owner only for create/update; other roles list only their allowed locations).
- Products: POST/GET/PATCH /products with pagination and search by name (owner/manager write; all roles read). Name unique per business, return a clear 409 on duplicates. Soft-deactivate via is_active, no hard delete.
- Staff: POST /staff (owner only) creates a user + membership with role manager or salesperson and assigns location ids; GET /staff lists the business's members; PATCH /staff/{membership_id} updates role, active flag and assigned locations.
Every query must filter by business_id from AuthContext. Add tests proving a user from business A gets 404 for business B's location and product ids.
```

## Step 4: Periods
```
Implement periods:
- POST /locations/{location_id}/periods: opens the first period for a location (body: start_date). Return 409 if an open period already exists. Calculate end_date from business_settings.period_length. Also create a period_counts row for every active product with opening_qty 0, opening_unit_cost 0 and selling_price from the product.
- GET /locations/{location_id}/periods (list) and GET /periods/{period_id} (detail including its counts).
Use the location access dependency. Wrap creation in a transaction. Add tests.
```

## Step 5: Stock entries
```
Implement stock entries:
- POST /periods/{period_id}/stock-entries: body { product_id, quantity, buying_price, entry_date }. Reject if the period is closed (409), the date is outside the period, quantity <= 0, or the product is not in this business. If the product has no count row in this period yet (new product), create it with opening_qty 0.
- GET /periods/{period_id}/stock-entries (optional product_id filter)
- DELETE /stock-entries/{id} (only while the period is open; owner/manager only)
Salespersons may add entries only for their assigned locations. Add tests including the closed-period rejection.
```

## Step 6: Calculations (pure functions first)
```
Create app/services/calculations.py with PURE functions using decimal.Decimal and no DB access:
- compute_available(opening_qty, entries)
- compute_weighted_average_cost(opening_qty, opening_unit_cost, entries)
- compute_sold(available, unsold_qty, lost_damaged_qty)  # raises AppError if negative
- compute_product_result(opening_qty, opening_unit_cost, entries, unsold_qty, lost_damaged_qty, selling_price) returning a dataclass with: available, sold, unit_cost, revenue, cost_of_sold, profit
Round money to 2 decimals only at the end (ROUND_HALF_UP). Write pytest tests including this hand-calculated case:
 opening 10 @ cost 100; entries: 20 @ 130; unsold 5; lost/damaged 1; selling price 200
 expected: available 30, avg cost 120, sold 24, revenue 4800, cost_of_sold 2880, profit 1920
Also test: no entries, available = 0, and a negative sold result being rejected.
```

## Step 7: Counts
```
Implement counts:
- GET /periods/{period_id}/counts: each row with live computed figures using calculations.py (draft numbers while the period is open).
- PUT /periods/{period_id}/counts/{product_id}: body { unsold_qty, lost_damaged_qty?, selling_price? }. Reject if the period is closed or if unsold_qty > opening + entries. Set recorded_by.
- PUT /periods/{period_id}/counts (bulk) accepting a list, in one transaction.
Add tests.
```

## Step 8: Close period (the critical one)
```
Implement POST /periods/{period_id}/close (owner/manager, with location access), exactly as described under "Closing a period" in the project instructions, in one transaction using transaction():
1. lock the period row (SELECT ... FOR UPDATE) and ensure it is open
2. ensure every count row has unsold_qty set; otherwise return 422 listing the missing products
3. compute each product's result with calculations.py and store unit_cost_used
4. mark the period closed
5. create the next period and its count rows, carrying unsold_qty into opening_qty and unit_cost_used into opening_unit_cost
Return the closed period summary and the new period id.
Write integration tests covering: success, missing counts, already closed, and carry-over of opening quantity and cost into the next period. Use the numbers from Step 6.
```

## Step 9: Reports
```
Implement GET /reports/summary with query params date_from, date_to, location_id (optional), product_id (optional).
- Include only CLOSED periods whose dates fall within the range.
- Return per-product and total: sold, revenue, cost_of_sold, profit, plus a per-location breakdown.
- If location_id is omitted, include only the locations the user may access (owners: all).
- Compute with calculations.py, not in SQL.
Add tests, including a user restricted to one location not seeing others.
```

## Step 10: Hardening
```
Review the whole codebase against the "Multi-tenancy rules" in the project instructions. List every SQL query on a tenant table that lacks a business_id filter, and fix them. Then add tests/test_tenant_isolation.py that creates two businesses and verifies that for every endpoint, business A cannot read or modify business B's data (expect 404). Add rate limiting on /auth routes with slowapi, CORS configuration, and make sure OpenAPI docs at /docs describe every endpoint with request and response models and tags.
```

---

## If the agent goes wrong
- Ask it: "Explain what you changed and which rules from the instructions it follows."
- If it edits the schema, uses float for money, or skips tenant scoping, reply: "That violates the project instructions. Revert that part and follow them."
- If it switches to async def with blocking DB calls or introduces the ORM, remind it of the Stack section.
- Keep steps small. If a step fails twice, split it into two prompts.
