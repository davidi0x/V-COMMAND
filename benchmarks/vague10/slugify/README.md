# slugs

Conventions of this package:

- Output uses `-` as the separator and only the characters `a-z`, `0-9` and `-`.
- No leading, trailing or repeated dashes.
- Accents are transliterated to ASCII with the standard library (`é` -> `e`).
- A non-string argument raises `errors.ValidationError`.
