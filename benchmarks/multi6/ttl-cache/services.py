import backend


def get_price(sku):
    """Current price."""
    return backend.load_price(sku)


def get_stock(sku):
    """Units in stock."""
    return backend.load_stock(sku)
