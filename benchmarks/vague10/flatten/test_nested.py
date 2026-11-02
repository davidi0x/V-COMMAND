import unittest
from errors import ValidationError
from nested import flatten

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(flatten([1, [2, [3, (4,)]]]), [1, 2, 3, 4])
    def test_strings(self): self.assertEqual(flatten(["ab", ["cd"]]), ["ab", "cd"])
    def test_dict_bytes(self): self.assertEqual(flatten([{"a": 1}, [b"x"]]), [{"a": 1}, b"x"])
    def test_depth(self): self.assertEqual(flatten([1, [2, [3]]], depth=1), [1, 2, [3]])
    def test_depth0(self):
        xs = [1, [2]]; r = flatten(xs, depth=0); self.assertEqual(r, [1, [2]]); self.assertIsNot(r, xs)
    def test_no_mutation(self):
        xs = [1, [2, [3]]]; flatten(xs); self.assertEqual(xs, [1, [2, [3]]])
    def test_depth_invalid(self):
        for bad in (-1, 1.5, "1", True):
            with self.assertRaises(ValidationError): flatten([1], depth=bad)

if __name__ == "__main__": unittest.main()
