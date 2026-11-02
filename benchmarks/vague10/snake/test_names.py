import unittest
from errors import ValidationError
from names import camel_to_snake

class T(unittest.TestCase):
    def test_simple(self): self.assertEqual(camel_to_snake("userName"), "user_name")
    def test_acronym_start(self): self.assertEqual(camel_to_snake("HTTPServerError"), "http_server_error")
    def test_acronym_end(self): self.assertEqual(camel_to_snake("userID"), "user_id")
    def test_digits(self): self.assertEqual(camel_to_snake("parseJSON2Text"), "parse_json2_text")
    def test_snake(self): self.assertEqual(camel_to_snake("already_snake"), "already_snake")
    def test_empty(self): self.assertEqual(camel_to_snake(""), "")
    def test_type(self):
        with self.assertRaises(ValidationError): camel_to_snake(None)

if __name__ == "__main__": unittest.main()
