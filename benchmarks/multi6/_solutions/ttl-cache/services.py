import backend
from cache import cached


@cached(60)
def get_price(sku):
    """Current price."""
    return backend.load_price(sku)


@cached(5)
def get_stock(sku):
    """Units in stock."""
    return backend.load_stock(sku)
