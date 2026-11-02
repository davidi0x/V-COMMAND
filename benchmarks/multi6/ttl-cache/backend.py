CALLS = {"price": 0, "stock": 0}
PRICES = {"A1": 9.99, "B2": 24.5}
STOCK = {"A1": 3, "B2": 0}


def load_price(sku):
    CALLS["price"] += 1
    return PRICES[sku]


def load_stock(sku):
    CALLS["stock"] += 1
    return STOCK[sku]
