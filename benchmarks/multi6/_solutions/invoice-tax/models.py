from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    price: float
    qty: int = 1
    tax_rate: float = 0.0

    def subtotal(self):
        return round(self.price * self.qty, 2)

    def tax(self):
        return round(self.subtotal() * self.tax_rate, 2)

    def gross(self):
        return round(self.subtotal() + self.tax(), 2)
