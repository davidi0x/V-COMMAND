import unittest
from errors import ValidationError
from retry import retry_delays

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(retry_delays(4, 1, 100), (1, 2, 4, 8))
    def test_cap(self): self.assertEqual(retry_delays(5, 1, 6), (1, 2, 4, 6, 6))
    def test_float(self): self.assertEqual(retry_delays(3, 0.1, 10), (0.1, 0.2, 0.4))
    def test_round(self): self.assertEqual(retry_delays(2, 0.3333, 10), (0.333, 0.667))
    def test_tuple(self): self.assertIsInstance(retry_delays(1, 1, 1), tuple)
    def test_invalid(self):
        for args in ((0, 1, 2), (1.5, 1, 2), (True, 1, 2), (2, 0, 2), (2, -1, 2), (2, 5, 1), (2, "1", 5)):
            with self.assertRaises(ValidationError): retry_delays(*args)

if __name__ == "__main__": unittest.main()
