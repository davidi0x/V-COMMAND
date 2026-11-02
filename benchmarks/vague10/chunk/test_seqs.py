import unittest
from errors import ValidationError
from seqs import chunk

class T(unittest.TestCase):
    def test_even(self): self.assertEqual(chunk([1, 2, 3, 4], 2), [(1, 2), (3, 4)])
    def test_last_short(self): self.assertEqual(chunk([1, 2, 3], 2), [(1, 2), (3,)])
    def test_empty(self): self.assertEqual(chunk([], 3), [])
    def test_iterable(self): self.assertEqual(chunk(iter("abcde"), 2), [("a", "b"), ("c", "d"), ("e",)])
    def test_tuples(self): self.assertTrue(all(isinstance(c, tuple) for c in chunk(range(5), 2)))
    def test_no_mutation(self):
        xs = [1, 2, 3]; chunk(xs, 2); self.assertEqual(xs, [1, 2, 3])
    def test_size(self):
        for bad in (0, -1, 1.5, "2", True):
            with self.assertRaises(ValidationError): chunk([1], bad)

if __name__ == "__main__": unittest.main()
