import unittest
from errors import ValidationError
from ranges import merge_intervals

class T(unittest.TestCase):
    def test_overlap(self): self.assertEqual(merge_intervals([(1, 3), (2, 6)]), [(1, 6)])
    def test_touching(self): self.assertEqual(merge_intervals([(1, 2), (2, 3)]), [(1, 3)])
    def test_unsorted(self): self.assertEqual(merge_intervals([(8, 10), (1, 3), (2, 6)]), [(1, 6), (8, 10)])
    def test_contained(self): self.assertEqual(merge_intervals([(1, 10), (2, 3)]), [(1, 10)])
    def test_empty(self): self.assertEqual(merge_intervals([]), [])
    def test_no_mutation(self):
        xs = [(5, 6), (1, 2)]; merge_intervals(xs); self.assertEqual(xs, [(5, 6), (1, 2)])
    def test_invalid(self):
        with self.assertRaises(ValidationError): merge_intervals([(3, 1)])

if __name__ == "__main__": unittest.main()
