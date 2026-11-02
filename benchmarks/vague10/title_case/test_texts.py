import unittest
from errors import ValidationError
from texts import title_case

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(title_case("the lord of the rings"), "The Lord of the Rings")
    def test_last(self): self.assertEqual(title_case("what is it on"), "What Is It On")
    def test_spaces(self): self.assertEqual(title_case("  war   and peace "), "War and Peace")
    def test_upper(self): self.assertEqual(title_case("HELLO WORLD"), "Hello World")
    def test_single(self): self.assertEqual(title_case("of"), "Of")
    def test_empty(self): self.assertEqual(title_case(""), "")
    def test_type(self):
        with self.assertRaises(ValidationError): title_case(3)

if __name__ == "__main__": unittest.main()
