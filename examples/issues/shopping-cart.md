# Checkout totals are wrong for multi-quantity items and coupons

Customers report wrong totals at checkout:

- 4 notebooks at $4.50 show a line total of $8.50 instead of $18.00
  (`test_line_total_multiplies_quantity` and `test_subtotal` fail).
- The `SAVE10` coupon on a $200 cart gives $0 instead of $180
  (`test_percentage_coupon` fails).

Suspected causes, in two different modules:

1. In `shopcart/models.py`, `return self.unit_price + self.quantity` should be `return self.unit_price * self.quantity`.
2. In `shopcart/pricing.py`, `discount = subtotal * coupon.percent` should be `discount = subtotal * coupon.percent / 100`.
