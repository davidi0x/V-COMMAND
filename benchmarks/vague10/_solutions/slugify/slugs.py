import re
import unicodedata

from errors import ValidationError


def slugify(text):
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
