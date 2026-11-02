class Invoice:
    def __init__(self, items):
        self.items = list(items)

    def total(self):
        return round(sum(i.gross() for i in self.items), 2)

    def tax_total(self):
        return round(sum(i.tax() for i in self.items), 2)
