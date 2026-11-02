# retry

Conventions of this package:

- `retry_delays(attempts, base, cap)` returns a **tuple** of `attempts` exponential backoff delays:
  `base * 2**i`, never above `cap`, each rounded to 3 decimals.
- `attempts` below 1 or not an int, or `base` / `cap` that are not positive numbers, raise
  `errors.ValidationError`. `cap` must be at least `base`.
