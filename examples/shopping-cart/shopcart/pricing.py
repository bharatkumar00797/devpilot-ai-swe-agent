"""Coupons, tax and checkout totals."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from shopcart.models import Cart

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Coupon:
    code: str
    percent: Decimal
    min_subtotal: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not Decimal("0") < self.percent <= Decimal("100"):
            raise ValueError("percent must be in (0, 100]")


def apply_coupon(subtotal: Decimal, coupon: Coupon | None) -> Decimal:
    """Return the subtotal after the coupon discount (never below zero)."""
    if coupon is None or subtotal < coupon.min_subtotal:
        return subtotal
    discount = subtotal * coupon.percent
    return max(subtotal - discount, Decimal("0"))


def checkout_total(
    cart: Cart, coupon: Coupon | None = None, tax_rate: Decimal = Decimal("0")
) -> Decimal:
    """Subtotal, minus coupon, plus tax, rounded to cents."""
    discounted = apply_coupon(cart.subtotal, coupon)
    total = discounted * (1 + tax_rate)
    return total.quantize(CENTS, rounding=ROUND_HALF_UP)
