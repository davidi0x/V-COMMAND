import unittest

from parser import parse
from report import render
from stats import summarize

CSV = "region,item,amount\r\nnorth,\"widget, large\",10.5\r\nsouth,gadget,4\r\nnorth,gizmo,\r\nnorth,\"say \"\"hi\"\"\",2.25\r\n"


class T(unittest.TestCase):
    def test_parse_quotes_and_crlf(self):
        rows = parse(CSV)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], {"region": "north", "item": "widget, large", "amount": "10.5"})
        self.assertEqual(rows[3]["item"], 'say "hi"')
        self.assertEqual(rows[2]["amount"], "")

    def test_parse_newline_in_quotes_and_lf(self):
        rows = parse('a,b\n1,"x\ny"\n')
        self.assertEqual(rows, [{"a": "1", "b": "x\ny"}])

    def test_parse_no_trailing_newline_and_empty(self):
        self.assertEqual(parse("a,b\n1,2"), [{"a": "1", "b": "2"}])
        self.assertEqual(parse("a,b\n"), [])
        self.assertEqual(parse(""), [])

    def test_parse_bad_row_names_the_line(self):
        with self.assertRaises(ValueError) as cm:
            parse("a,b\n1,2\n3\n")
        self.assertIn("3", str(cm.exception))

    def test_summarize(self):
        s = summarize(parse(CSV), "region", "amount")
        self.assertEqual(s["north"], {"count": 2, "sum": 12.75, "avg": 6.38})
        self.assertEqual(s["south"], {"count": 1, "sum": 4.0, "avg": 4.0})

    def test_summarize_blank_only_and_bad_value(self):
        s = summarize([{"k": "a", "v": ""}], "k", "v")
        self.assertEqual(s["a"], {"count": 0, "sum": 0.0, "avg": None})
        with self.assertRaises(ValueError):
            summarize([{"k": "a", "v": "x"}], "k", "v")

    def test_render(self):
        s = summarize(parse(CSV), "region", "amount")
        self.assertEqual(render(s), "key    count    sum   avg\nnorth      2  12.75  6.38\nsouth      1   4.00  4.00")

    def test_render_order_and_dash(self):
        s = {"b": {"count": 1, "sum": 5.0, "avg": 5.0}, "a": {"count": 1, "sum": 5.0, "avg": 5.0},
             "z": {"count": 0, "sum": 0.0, "avg": None}}
        lines = render(s).splitlines()
        self.assertEqual([l.split()[0] for l in lines[1:]], ["a", "b", "z"])
        self.assertTrue(lines[3].rstrip().endswith("-"))

    def test_pipeline(self):
        out = render(summarize(parse("team,pts\nred,3\nblue,9\nred,4\n"), "team", "pts"))
        self.assertEqual(out.splitlines()[1].split(), ["blue", "1", "9.00", "9.00"])


if __name__ == "__main__":
    unittest.main()
