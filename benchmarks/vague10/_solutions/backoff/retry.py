from errors import ValidationError


def _positive(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0


def retry_delays(attempts, base, cap):
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValidationError("attempts must be an int >= 1")
    if not _positive(base) or not _positive(cap) or cap < base:
        raise ValidationError("base and cap must be positive and cap >= base")
    return tuple(round(min(cap, base * 2 ** i), 3) for i in range(attempts))
