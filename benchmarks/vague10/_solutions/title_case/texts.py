from errors import ValidationError

SMALL = {"a", "an", "and", "of", "the", "in", "on"}


def title_case(text):
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    words = text.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        out.append(lw if lw in SMALL and 0 < i < len(words) - 1 else lw.capitalize())
    return " ".join(out)
