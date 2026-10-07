from decimal import Decimal

import pytest

from shopcart import Cart, CartItem, Coupon, apply_coupon, checkout_total


def make_cart() -> Cart:
    cart = Cart()
    cart.add(CartItem("BK-1", "Notebook", Decimal("4.50"), quantity=4))
    cart.add(CartItem("PN-2", "Pen", Decimal("1.25"), quantity=2))
    return cart


def test_line_total_multiplies_quantity() -> None:
    assert CartItem("BK-1", "Notebook", Decimal("4.50"), quantity=4).line_total == Decimal("18.00")


def test_adding_same_sku_merges_quantity() -> None:
    cart = Cart()
    cart.add(CartItem("PN-2", "Pen", Decimal("1.25")))
    cart.add(CartItem("PN-2", "Pen", Decimal("1.25"), quantity=3))
    assert cart.items["PN-2"].quantity == 4
    assert cart.subtotal == Decimal("5.00")


def test_subtotal() -> None:
    assert make_cart().subtotal == Decimal("20.50")


def test_percentage_coupon() -> None:
    assert apply_coupon(Decimal("200"), Coupon("SAVE10", Decimal("10"))) == Decimal("180")


def test_coupon_minimum_not_met() -> None:
    coupon = Coupon("BIG20", Decimal("20"), min_subtotal=Decimal("50"))
    assert apply_coupon(Decimal("49.99"), coupon) == Decimal("49.99")


def test_checkout_total_with_coupon_and_tax() -> None:
    total = checkout_total(make_cart(), Coupon("SAVE10", Decimal("10")), Decimal("0.08"))
    assert total == Decimal("19.93")


def test_invalid_quantity_rejected() -> None:
    with pytest.raises(ValueError):
        CartItem("X", "Broken", Decimal("1"), quantity=0)
