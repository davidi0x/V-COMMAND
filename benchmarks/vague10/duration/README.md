# durations

Conventions of this package:

- Input like `1h30m`, `90s`, `2d4h`: units `d`, `h`, `m`, `s`, case-insensitive, whitespace around is ignored.
- Returns an `int` number of seconds.
- Empty input, unknown units, a number without unit, or a non-string raise `errors.ValidationError`.
