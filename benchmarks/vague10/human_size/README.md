# sizes

Conventions of this package:

- Base 1024 with units `B`, `KB`, `MB`, `GB`, `TB`.
- Bytes are printed as an integer (`1023 B`); every other unit with exactly one decimal (`1.0 KB`, `1.5 MB`).
- Negative numbers, non-integers and booleans raise `errors.ValidationError`.
