"""Cart and line-item models."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class CartItem:
    sku: str
    name: str
    unit_price: Decimal
    quantity: int = 1

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError("quantity must be at least 1")
        if self.unit_price < 0:
            raise ValueError("unit_price cannot be negative")

    @property
    def line_total(self) -> Decimal:
        return self.unit_price + self.quantity


@dataclass
class Cart:
    items: dict[str, CartItem] = field(default_factory=dict)

    def add(self, item: CartItem) -> None:
        existing = self.items.get(item.sku)
        if existing is not None:
            item = CartItem(
                existing.sku,
                existing.name,
                existing.unit_price,
                existing.quantity + item.quantity,
            )
        self.items[item.sku] = item

    def remove(self, sku: str) -> None:
        self.items.pop(sku, None)

    @property
    def subtotal(self) -> Decimal:
        return sum((item.line_total for item in self.items.values()), Decimal("0"))
