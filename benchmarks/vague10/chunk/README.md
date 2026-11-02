# seqs

Conventions of this package:

- Splits any iterable into consecutive chunks of `size`; the last chunk may be shorter.
- Returns a list of **tuples** (not lists).
- `size` below 1 or not an int raises `errors.ValidationError`.
- Never mutates its argument; an empty iterable gives `[]`.
