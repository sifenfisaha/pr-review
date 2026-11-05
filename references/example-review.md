# Example review

A complete review of a fictional but typical PR, to calibrate depth, tone and structure. The PR: "Add coupon codes to checkout" in `acme/shop#412`, by a mid-level teammate, 11 files, +386/-41, CI green, description links the ticket and says "tested manually with a 50% code".

What the reviewer did before writing: read the ticket and description; predicted the shape (model + migration, apply-discount logic in `Cart`, validation, an admin way to create codes, tests, docs); noticed from `files.tsv` that there was no permission decorator change and no docs change; checked out the worktree; read `tests/test_cart.py` first, then `0031_coupon.py`, then `coupons.py` and `total.py`, then `callers.py` output for `Cart.total` (3 callers, one in the invoice PDF generator); ran `pytest tests/` (14 passed); deleted the discount line and re-ran (still 14 passed); tried a 100% coupon in a shell against the fixture cart.

---

# Review: Add coupon codes to checkout (acme/shop#412)

**Verdict:** Request changes. Two blocking items, both small; everything else is non-blocking.
**Risk:** Medium. Changes the total every order pays, and adds an admin write path.
**Depth:** standard, leaning deep on `total.py` and the admin route. Read all 11 files in full; ran the test suite in a worktree.

## Summary

Adds percentage and fixed-amount coupons: a `Coupon` model with code, kind, amount, `expires_at` and a usage cap; `Cart.apply_coupon` to validate and attach one; the discount folded into `Cart.total`; and an admin endpoint to create codes. The approach fits the codebase well: `Coupon.from_code` sits next to the other lookups, the discount is a `Money`, and the migration is additive. The one thing to fix before anything else is the order of operations in `Cart.total`: tax is computed before the discount is subtracted, so every discounted order over-pays tax, which is both a correctness and a legal problem in most of our markets.

## Blocking

1. **issue (blocking):** `src/billing/total.py:88`. `tax` is computed from `subtotal` on line 84, then `discount` is subtracted on line 88, so a 100% coupon on a $50 taxable item charges $4.00. Compute tax from the discounted amount, clamped at zero:
   ```python
   discounted = max(subtotal - discount, Money.zero())
   tax = (discounted * self.tax_rate).round_half_up()
   return discounted + tax
   ```
   Verified by applying `Coupon(kind="percent", amount=100)` to the fixture cart in a shell: total was `4.00`, expected `0.00`. The invoice PDF generator (`reports/invoice.py:120`) reads `Cart.total()` too, so it is also affected.
2. **issue (blocking):** `src/admin/routes.py:12-18`. The new `POST /admin/coupons` route has no `@require_role("admin")`; every other route in this file has one. As written, any logged-in user can create a 100% coupon. Adding the decorator matches the file; a test in `tests/admin/test_routes.py` for a non-admin getting a 403 would keep it that way (the other routes have that test).

## Should fix

3. **suggestion:** `tests/test_cart.py:41`. `test_apply_percent_coupon` calls `apply_coupon` and asserts the coupon is attached, but never asserts the total. It passes with the discount line deleted (I tried). Asserting `cart.total() == Money("27.00")` (50% of 50.00 plus 8% tax on 25.00) would pin the behavior and would have caught item 1.
4. **todo:** `src/billing/coupons.py:31`. `expires_at` is stored and set by the admin endpoint but never read; expired codes are accepted. One comparison in `Coupon.is_valid` against `clock.now()` (the codebase injects the clock, see `billing/clock.py`) plus a test.
5. **issue (non-blocking):** `migrations/0031_coupon.py:14`. The unique index on `code` is case-sensitive while `from_code` lowercases its input, so `SAVE10` and `save10` can both be created and only `save10` is ever found. Either normalise on write (in the model's `save`/`clean`) or index `lower(code)`. Not blocking because the admin form is the only writer today.

## Nits

6. **nitpick (non-blocking):** `src/billing/coupons.py:40-60`. `c` for a coupon across twenty lines; `coupon` would read without a scroll.
7. **nitpick (non-blocking):** `src/billing/total.py:80`. The comment says "apply discount" above the tax line; after the fix in item 1 it will be in the right place anyway.

## Questions

8. **question:** `src/billing/coupons.py:52`. `max_uses` is decremented on `apply_coupon`, which runs when the cart is updated, not when the order is placed. Is a coupon meant to be consumed by adding it to a cart that is then abandoned? If the intent is per-order, the decrement belongs in `orders.place()`, and it will need to be atomic (`F("uses") + 1` or `select_for_update`) since two checkouts can race on the last use.

## Missing from the diff

- Expiry check (item 4).
- Permission check on the admin route (item 2).
- `docs/admin.md` lists admin capabilities; coupons are not mentioned.
- No test for the fixed-amount kind exceeding the subtotal (should clamp to zero, which the fix in item 1 handles; worth a test).

## Tests

CI: lint, unit and integration all green. Locally in a worktree: `pytest tests/` gives 14 passed in 3.2s. With the discount subtraction removed from `Cart.total`, still 14 passed, which is why item 3 matters. Not covered anywhere: expiry, non-admin access to the new route, the fixed-amount clamp, the race in item 8.

## Praise

- `Coupon.from_code` stripping whitespace and lowercasing before lookup is the kind of detail that saves a week of "my code doesn't work" tickets.
- Using `Money` throughout instead of raw `Decimal` kept the rounding in one place; the fix in item 1 is three lines because of it.

## Out of scope

- `Cart.total` recomputes line totals on every call and is called four times per checkout page render. Pre-existing; happy to file an issue.

---

## The same review as `review.json`

The summary becomes `body`; items with a stable line become inline comments; items that span several lines use `start_line`; section-level notes stay in the body. Lines come from the worktree, checked against `diff.patch` so they are inside hunks.

```json
{
  "repo": "acme/shop",
  "pr": 412,
  "event": "REQUEST_CHANGES",
  "body": "**Verdict:** Request changes. Two blocking items, both small ...\n\n## Summary\n...\n\n## Missing from the diff\n...\n\n## Tests\n...\n\n## Praise\n...",
  "comments": [
    {"path": "src/billing/total.py", "line": 88, "body": "**issue (blocking):** `tax` is computed from `subtotal` on line 84 ... ```suggestion\n ... ```"},
    {"path": "src/admin/routes.py", "start_line": 12, "line": 18, "body": "**issue (blocking):** no `@require_role(\"admin\")` ..."},
    {"path": "tests/test_cart.py", "line": 41, "body": "**suggestion:** asserts the coupon is attached but never the total ..."},
    {"path": "src/billing/coupons.py", "line": 31, "body": "**todo:** `expires_at` is never read ..."},
    {"path": "migrations/0031_coupon.py", "line": 14, "body": "**issue (non-blocking):** case-sensitive unique index ..."},
    {"path": "src/billing/coupons.py", "line": 52, "body": "**question:** `max_uses` is decremented on apply, not on order ..."},
    {"path": "src/billing/coupons.py", "line": 40, "body": "**nitpick (non-blocking):** `c` for a coupon across twenty lines ..."}
  ]
}
```

What made this review useful: the verdict and the most important problem are in the first three lines; every finding names the input that triggers it; the reviewer said what they ran and what they could not cover; the author knows exactly which two things stand between them and a merge; and the praise is specific enough to be believed.
