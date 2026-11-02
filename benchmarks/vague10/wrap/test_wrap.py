import unittest
from errors import ValidationError
from wrap import word_wrap

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(word_wrap("the quick brown fox", 10), ["the quick", "brown fox"])
    def test_exact(self): self.assertEqual(word_wrap("abc def", 7), ["abc def"])
    def test_long_word(self): self.assertEqual(word_wrap("abcdefghij", 4), ["abcd", "efgh", "ij"])
    def test_paragraphs(self): self.assertEqual(word_wrap("a b\n\nc d", 3), ["a b", "", "c d"])
    def test_spaces(self): self.assertEqual(word_wrap("a    b", 10), ["a b"])
    def test_empty(self): self.assertEqual(word_wrap("", 5), [""])
    def test_width(self):
        for bad in (0, -2, 2.5, "3", True):
            with self.assertRaises(ValidationError): word_wrap("x", bad)

if __name__ == "__main__": unittest.main()
