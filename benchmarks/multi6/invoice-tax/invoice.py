class Invoice:
    def __init__(self, items):
        self.items = list(items)

    def total(self):
        return round(sum(i.subtotal() for i in self.items), 2)
