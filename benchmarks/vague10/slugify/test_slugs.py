import unittest
from errors import ValidationError
from slugs import slugify

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(slugify("Hello World"), "hello-world")
    def test_punctuation(self): self.assertEqual(slugify("Hello, World!!"), "hello-world")
    def test_repeated(self): self.assertEqual(slugify("a  --  b"), "a-b")
    def test_trim(self): self.assertEqual(slugify("  --Hi--  "), "hi")
    def test_accents(self): self.assertEqual(slugify("Crème brûlée"), "creme-brulee")
    def test_empty(self): self.assertEqual(slugify(""), "")
    def test_digits(self): self.assertEqual(slugify("Top 10 of 2024"), "top-10-of-2024")
    def test_type(self):
        for bad in (None, 5, b"x"):
            with self.assertRaises(ValidationError): slugify(bad)

if __name__ == "__main__": unittest.main()
