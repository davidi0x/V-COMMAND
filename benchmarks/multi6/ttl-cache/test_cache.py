import unittest

import backend
import cache
import services


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class T(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        cache.set_clock(self.clock)
        cache.clear_cache()
        backend.CALLS.update(price=0, stock=0)

    def test_hit_and_miss(self):
        self.assertEqual(services.get_price("A1"), 9.99)
        self.assertEqual(services.get_price("A1"), 9.99)
        self.assertEqual(backend.CALLS["price"], 1)
        services.get_price("B2")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_args_and_kwargs_share_entry(self):
        services.get_price("A1")
        services.get_price(sku="A1")
        self.assertEqual(backend.CALLS["price"], 1)

    def test_expiry_per_function(self):
        services.get_price("A1")
        services.get_stock("A1")
        self.clock.now += 6
        services.get_price("A1")
        services.get_stock("A1")
        self.assertEqual((backend.CALLS["price"], backend.CALLS["stock"]), (1, 2))  # stock ttl 5, price ttl 60
        self.clock.now += 60
        services.get_price("A1")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_exceptions_not_cached(self):
        for _ in range(2):
            with self.assertRaises(KeyError):
                services.get_price("ZZ")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_clear_cache(self):
        services.get_price("A1")
        cache.clear_cache()
        services.get_price("A1")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_metadata_preserved(self):
        self.assertEqual(services.get_price.__name__, "get_price")
        self.assertEqual(services.get_stock.__doc__, "Units in stock.")

    def test_falsy_values_are_cached(self):
        self.assertEqual(services.get_stock("B2"), 0)
        self.assertEqual(services.get_stock("B2"), 0)
        self.assertEqual(backend.CALLS["stock"], 1)


if __name__ == "__main__":
    unittest.main()
