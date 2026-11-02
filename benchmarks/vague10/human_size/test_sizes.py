import unittest
from errors import ValidationError
from sizes import human_size

class T(unittest.TestCase):
    def test_zero(self): self.assertEqual(human_size(0), "0 B")
    def test_edge(self): self.assertEqual(human_size(1023), "1023 B")
    def test_kb(self): self.assertEqual(human_size(1024), "1.0 KB")
    def test_mb(self): self.assertEqual(human_size(1536 * 1024), "1.5 MB")
    def test_gb(self): self.assertEqual(human_size(3 * 1024 ** 3), "3.0 GB")
    def test_tb(self): self.assertEqual(human_size(5 * 1024 ** 4), "5.0 TB")
    def test_invalid(self):
        for bad in (-1, 1.5, "1", None, True):
            with self.assertRaises(ValidationError): human_size(bad)

if __name__ == "__main__": unittest.main()
