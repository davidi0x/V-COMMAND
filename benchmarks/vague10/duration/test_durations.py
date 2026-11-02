import unittest
from errors import ValidationError
from durations import parse_duration

class T(unittest.TestCase):
    def test_seconds(self): self.assertEqual(parse_duration("90s"), 90)
    def test_combined(self): self.assertEqual(parse_duration("1h30m"), 5400)
    def test_days(self): self.assertEqual(parse_duration("2d4h"), 2 * 86400 + 4 * 3600)
    def test_case_space(self): self.assertEqual(parse_duration("  1H 5M".replace(" 5M", "5M")), 3900)
    def test_int(self): self.assertIs(type(parse_duration("1m")), int)
    def test_invalid(self):
        for bad in ("", "  ", "10", "5x", "h", "1h2", None, 90):
            with self.assertRaises(ValidationError): parse_duration(bad)

if __name__ == "__main__": unittest.main()
