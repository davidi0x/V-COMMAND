from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    price: float
    qty: int = 1

    def subtotal(self):
        return round(self.price * self.qty, 2)
