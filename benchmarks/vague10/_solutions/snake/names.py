import re

from errors import ValidationError


def camel_to_snake(name):
    if not isinstance(name, str):
        raise ValidationError("name must be a string")
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()
