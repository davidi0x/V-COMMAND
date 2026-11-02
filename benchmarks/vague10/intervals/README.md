# ranges

Conventions of this package:

- Input: a list of `(start, end)` tuples, possibly unsorted.
- Overlapping **and touching** intervals (`end == next start`) are merged.
- Returns a new list of tuples sorted by start; the input is never mutated.
- An interval with `start > end` raises `errors.ValidationError`.
