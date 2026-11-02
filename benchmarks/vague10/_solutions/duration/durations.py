import re

from errors import ValidationError

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    s = text.strip().lower()
    if not s or not re.fullmatch(r"(\d+[dhms])+", s):
        raise ValidationError(f"invalid duration: {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in re.findall(r"(\d+)([dhms])", s))
