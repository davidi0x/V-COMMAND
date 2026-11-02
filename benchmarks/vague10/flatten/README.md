# nested

Conventions of this package:

- Flattens nested lists and tuples into a single list, in order.
- Strings, bytes and dicts are leaves: they are never flattened.
- Optional `depth` (default `None` = fully); `depth=0` returns a shallow copy; a negative or non-int depth raises
  `errors.ValidationError`.
- The input is never mutated.
