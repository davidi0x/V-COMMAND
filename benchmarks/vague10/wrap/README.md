# wrap

Conventions of this package:

- Returns a **list of lines**, each at most `width` characters.
- Words are separated by single spaces; a word longer than `width` is split across lines.
- Blank lines in the input (paragraph breaks) are preserved as empty strings in the output.
- `width` below 1 or not an int raises `errors.ValidationError`.
