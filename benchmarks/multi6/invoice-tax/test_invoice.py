import io
import unittest
from contextlib import redirect_stdout

from cli import main, parse_item
from invoice import Invoice
from models import Item
from render import render


class T(unittest.TestCase):
    def test_default_rate_is_zero(self):
        it = Item("pen", 2.0, 3)
        self.assertEqual((it.tax_rate, it.tax(), it.gross()), (0.0, 0.0, 6.0))

    def test_tax_and_gross(self):
        it = Item("lamp", 10.0, 2, 0.2)
        self.assertEqual((it.subtotal(), it.tax(), it.gross()), (20.0, 4.0, 24.0))

    def test_rounding(self):
        it = Item("x", 0.33, 3, 0.07)
        self.assertEqual((it.subtotal(), it.tax(), it.gross()), (0.99, 0.07, 1.06))

    def test_invoice_totals(self):
        inv = Invoice([Item("a", 10.0, 1, 0.1), Item("b", 5.0, 2)])
        self.assertEqual((inv.tax_total(), inv.total()), (1.0, 21.0))

    def test_render_untaxed_unchanged(self):
        inv = Invoice([Item("pen", 2.0, 3)])
        self.assertEqual(render(inv), "pen x3 @ 2.00 = 6.00\nTOTAL 6.00")

    def test_render_taxed(self):
        inv = Invoice([Item("lamp", 10.0, 2, 0.2), Item("pen", 2.0, 1)])
        self.assertEqual(render(inv), "lamp x2 @ 10.00 = 20.00 + tax 4.00\npen x1 @ 2.00 = 2.00\nTAX 4.00\nTOTAL 26.00")

    def test_cli_optional_rate(self):
        self.assertEqual(parse_item("a:1.5:2"), Item("a", 1.5, 2, 0.0))
        self.assertEqual(parse_item("a:1.5:2:0.25"), Item("a", 1.5, 2, 0.25))
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["lamp:10:2:0.2", "pen:2:1"])
        self.assertTrue(buf.getvalue().strip().endswith("TAX 4.00\nTOTAL 26.00"))


if __name__ == "__main__":
    unittest.main()
