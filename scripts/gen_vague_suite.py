#!/usr/bin/env python3
"""Generate benchmarks/vague10: ten tasks whose goal is one short sentence.

The requirements that the hidden tests check (which exception, "never mutate the input", return type,
edge cases) are written only in the task repository's README.md. A prompt that makes the agent read and
apply the repository's own conventions should do better than the bare goal — or it should not, and then
the numbers say so. Every task has a reference solution in `_solutions/<id>/`; CI verifies that the task
fails without it and passes with it.

Run: python scripts/gen_vague_suite.py   (rewrites benchmarks/vague10)
"""
from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "benchmarks" / "vague10"

ERRORS = '''class ValidationError(Exception):
    """Raised for every invalid argument in this package (never ValueError or TypeError)."""
'''

TASKS = [
    dict(
        id="slugify", module="slugs", func="slugify", goal="Implement slugify() in slugs.py.",
        readme="""- Output uses `-` as the separator and only the characters `a-z`, `0-9` and `-`.
- No leading, trailing or repeated dashes.
- Accents are transliterated to ASCII with the standard library (`é` -> `e`).
- A non-string argument raises `errors.ValidationError`.
""",
        stub='def slugify(text):\n    raise NotImplementedError\n',
        solution='''import re
import unicodedata

from errors import ValidationError


def slugify(text):
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
''',
        test='''import unittest
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
''',
    ),
    dict(
        id="duration", module="durations", func="parse_duration", goal="Add parse_duration() to durations.py.",
        readme="""- Input like `1h30m`, `90s`, `2d4h`: units `d`, `h`, `m`, `s`, case-insensitive, whitespace around is ignored.
- Returns an `int` number of seconds.
- Empty input, unknown units, a number without unit, or a non-string raise `errors.ValidationError`.
""",
        stub='def parse_duration(text):\n    raise NotImplementedError\n',
        solution='''import re

from errors import ValidationError

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    s = text.strip().lower()
    if not s or not re.fullmatch(r"(\\d+[dhms])+", s):
        raise ValidationError(f"invalid duration: {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in re.findall(r"(\\d+)([dhms])", s))
''',
        test='''import unittest
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
''',
    ),
    dict(
        id="chunk", module="seqs", func="chunk", goal="Write chunk(items, size) in seqs.py.",
        readme="""- Splits any iterable into consecutive chunks of `size`; the last chunk may be shorter.
- Returns a list of **tuples** (not lists).
- `size` below 1 or not an int raises `errors.ValidationError`.
- Never mutates its argument; an empty iterable gives `[]`.
""",
        stub='def chunk(items, size):\n    raise NotImplementedError\n',
        solution='''from errors import ValidationError


def chunk(items, size):
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValidationError("size must be an int >= 1")
    data = tuple(items)
    return [data[i:i + size] for i in range(0, len(data), size)]
''',
        test='''import unittest
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
''',
    ),
    dict(
        id="intervals", module="ranges", func="merge_intervals", goal="Implement merge_intervals() in ranges.py.",
        readme="""- Input: a list of `(start, end)` tuples, possibly unsorted.
- Overlapping **and touching** intervals (`end == next start`) are merged.
- Returns a new list of tuples sorted by start; the input is never mutated.
- An interval with `start > end` raises `errors.ValidationError`.
""",
        stub='def merge_intervals(intervals):\n    raise NotImplementedError\n',
        solution='''from errors import ValidationError


def merge_intervals(intervals):
    items = []
    for start, end in intervals:
        if start > end:
            raise ValidationError(f"invalid interval ({start}, {end})")
        items.append((start, end))
    items.sort()
    merged = []
    for start, end in items:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
''',
        test='''import unittest
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
''',
    ),
    dict(
        id="human_size", module="sizes", func="human_size", goal="Add human_size() to sizes.py.",
        readme="""- Base 1024 with units `B`, `KB`, `MB`, `GB`, `TB`.
- Bytes are printed as an integer (`1023 B`); every other unit with exactly one decimal (`1.0 KB`, `1.5 MB`).
- Negative numbers, non-integers and booleans raise `errors.ValidationError`.
""",
        stub='def human_size(n):\n    raise NotImplementedError\n',
        solution='''from errors import ValidationError


def human_size(n):
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValidationError("n must be a non-negative int")
    if n < 1024:
        return f"{n} B"
    size = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
''',
        test='''import unittest
from errors import ValidationError
from sizes import human_size

class T(unittest.TestCase):
    def test_zero(self): self.assertEqual(human_size(0), "0 B")
    def test_edge(self): self.assertEqual(human_size(1023), "1023 B")
    def test_kb(self): self.assertEqual(human_size(1024), "1.0 KB")
    def test_mb(self): self.assertEqual(human_size(1536 * 1024), "1.5 MB")
    def test_gb(self): self.assertEqual(human_size(3 * 1024 ** 3), "3.0 GB")
    def test_tb(self): self.assertEqual(human_size(5 * 1024 ** 4), "5.0 TB")
    def test_invalid(self):
        for bad in (-1, 1.5, "1", None, True):
            with self.assertRaises(ValidationError): human_size(bad)

if __name__ == "__main__": unittest.main()
''',
    ),
    dict(
        id="snake", module="names", func="camel_to_snake", goal="Implement camel_to_snake() in names.py.",
        readme="""- `HTTPServerError` -> `http_server_error`, `userID` -> `user_id`, `parseJSON2Text` -> `parse_json2_text`.
- Strings that are already snake_case are returned unchanged; the empty string stays empty.
- A non-string argument raises `errors.ValidationError`.
""",
        stub='def camel_to_snake(name):\n    raise NotImplementedError\n',
        solution='''import re

from errors import ValidationError


def camel_to_snake(name):
    if not isinstance(name, str):
        raise ValidationError("name must be a string")
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\\1_\\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\\1_\\2", s)
    return s.lower()
''',
        test='''import unittest
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
''',
    ),
    dict(
        id="title_case", module="texts", func="title_case", goal="Write title_case() in texts.py.",
        readme="""- Capitalizes each word, except the small words `a an and of the in on` which stay lowercase.
- The first and the last word are always capitalized.
- Words are separated by single spaces in the output; surrounding whitespace is dropped.
- A non-string argument raises `errors.ValidationError`.
""",
        stub='def title_case(text):\n    raise NotImplementedError\n',
        solution='''from errors import ValidationError

SMALL = {"a", "an", "and", "of", "the", "in", "on"}


def title_case(text):
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    words = text.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        out.append(lw if lw in SMALL and 0 < i < len(words) - 1 else lw.capitalize())
    return " ".join(out)
''',
        test='''import unittest
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
''',
    ),
    dict(
        id="flatten", module="nested", func="flatten", goal="Implement flatten() in nested.py.",
        readme="""- Flattens nested lists and tuples into a single list, in order.
- Strings, bytes and dicts are leaves: they are never flattened.
- Optional `depth` (default `None` = fully); `depth=0` returns a shallow copy; a negative or non-int depth raises
  `errors.ValidationError`.
- The input is never mutated.
""",
        stub='def flatten(items, depth=None):\n    raise NotImplementedError\n',
        solution='''from errors import ValidationError


def flatten(items, depth=None):
    if depth is not None and (isinstance(depth, bool) or not isinstance(depth, int) or depth < 0):
        raise ValidationError("depth must be None or an int >= 0")
    out = []

    def walk(seq, d):
        for x in seq:
            if isinstance(x, (list, tuple)) and (d is None or d > 0):
                walk(x, None if d is None else d - 1)
            else:
                out.append(x)

    walk(items, depth)
    return out
''',
        test='''import unittest
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
''',
    ),
    dict(
        id="wrap", module="wrap", func="word_wrap", goal="Add word_wrap(text, width) to wrap.py.",
        readme="""- Returns a **list of lines**, each at most `width` characters.
- Words are separated by single spaces; a word longer than `width` is split across lines.
- Blank lines in the input (paragraph breaks) are preserved as empty strings in the output.
- `width` below 1 or not an int raises `errors.ValidationError`.
""",
        stub='def word_wrap(text, width):\n    raise NotImplementedError\n',
        solution='''from errors import ValidationError


def word_wrap(text, width):
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValidationError("width must be an int >= 1")
    lines = []
    for paragraph in text.split("\\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            while len(w) > width:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(w[:width])
                w = w[width:]
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines
''',
        test='''import unittest
from errors import ValidationError
from wrap import word_wrap

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(word_wrap("the quick brown fox", 10), ["the quick", "brown fox"])
    def test_exact(self): self.assertEqual(word_wrap("abc def", 7), ["abc def"])
    def test_long_word(self): self.assertEqual(word_wrap("abcdefghij", 4), ["abcd", "efgh", "ij"])
    def test_paragraphs(self): self.assertEqual(word_wrap("a b\\n\\nc d", 3), ["a b", "", "c d"])
    def test_spaces(self): self.assertEqual(word_wrap("a    b", 10), ["a b"])
    def test_empty(self): self.assertEqual(word_wrap("", 5), [""])
    def test_width(self):
        for bad in (0, -2, 2.5, "3", True):
            with self.assertRaises(ValidationError): word_wrap("x", bad)

if __name__ == "__main__": unittest.main()
''',
    ),
    dict(
        id="backoff", module="retry", func="retry_delays", goal="Implement retry_delays() in retry.py.",
        readme="""- `retry_delays(attempts, base, cap)` returns a **tuple** of `attempts` exponential backoff delays:
  `base * 2**i`, never above `cap`, each rounded to 3 decimals.
- `attempts` below 1 or not an int, or `base` / `cap` that are not positive numbers, raise
  `errors.ValidationError`. `cap` must be at least `base`.
""",
        stub='def retry_delays(attempts, base, cap):\n    raise NotImplementedError\n',
        solution='''from errors import ValidationError


def _positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


def retry_delays(attempts, base, cap):
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValidationError("attempts must be an int >= 1")
    if not _positive(base) or not _positive(cap) or cap < base:
        raise ValidationError("base and cap must be positive and cap >= base")
    return tuple(round(min(cap, base * 2 ** i), 3) for i in range(attempts))
''',
        test='''import unittest
from errors import ValidationError
from retry import retry_delays

class T(unittest.TestCase):
    def test_basic(self): self.assertEqual(retry_delays(4, 1, 100), (1, 2, 4, 8))
    def test_cap(self): self.assertEqual(retry_delays(5, 1, 6), (1, 2, 4, 6, 6))
    def test_float(self): self.assertEqual(retry_delays(3, 0.1, 10), (0.1, 0.2, 0.4))
    def test_round(self): self.assertEqual(retry_delays(2, 0.3333, 10), (0.333, 0.667))
    def test_tuple(self): self.assertIsInstance(retry_delays(1, 1, 1), tuple)
    def test_invalid(self):
        for args in ((0, 1, 2), (1.5, 1, 2), (True, 1, 2), (2, 0, 2), (2, -1, 2), (2, 5, 1), (2, "1", 5)):
            with self.assertRaises(ValidationError): retry_delays(*args)

if __name__ == "__main__": unittest.main()
''',
    ),
]


def build(out: Path = OUT) -> None:
    if out.exists():
        shutil.rmtree(out)
    tasks = []
    for t in TASKS:
        d = out / t["id"]
        d.mkdir(parents=True)
        (d / "errors.py").write_text(ERRORS)
        (d / f"{t['module']}.py").write_text(t["stub"])
        (d / f"test_{t['module']}.py").write_text(t["test"])
        (d / "README.md").write_text(f"# {t['module']}\n\nConventions of this package:\n\n{t['readme']}")
        sol = out / "_solutions" / t["id"]
        sol.mkdir(parents=True)
        (sol / f"{t['module']}.py").write_text(t["solution"])
        tasks.append({"id": t["id"], "dir": t["id"], "goal": t["goal"], "focus": [],
                      "gates": [["python", "-B", f"test_{t['module']}.py"]]})
    (out / "suite.json").write_text(json.dumps({
        "name": "vague10",
        "description": ("Ten tasks with a one-sentence goal; the requirements the hidden tests check live only in "
                        "each repository's README.md. Measures whether reading and applying the repository's own "
                        "conventions (what a good brief makes explicit) changes the pass rate."),
        "tasks": tasks}, indent=2) + "\n")
    (out / "README.md").write_text(textwrap.dedent("""\
        # vague10

        Ten small Python tasks. The goal is one sentence; the exact requirements (exception type, return type,
        edge cases, "never mutate the input") are only in the README.md of each task repository.

        Regenerate: `python scripts/gen_vague_suite.py`. `_solutions/<id>/` holds the reference solutions
        (CI checks that each task fails without and passes with it).
        """))


if __name__ == "__main__":
    build()
    print(f"wrote {OUT}")
