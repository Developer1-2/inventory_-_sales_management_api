Implement counts:
- GET /periods/{period_id}/counts: each row with live computed figures using calculations.py (draft numbers while the period is open).
- PUT /periods/{period_id}/counts/{product_id}: body { unsold_qty, lost_damaged_qty?, selling_price? }. Reject if the period is closed or if unsold_qty > opening + entries. Set recorded_by.
- PUT /periods/{period_id}/counts (bulk) accepting a list, in one transaction.
Add tests.
```