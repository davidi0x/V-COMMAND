from errors import ValidationError


def word_wrap(text, width):
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValidationError("width must be an int >= 1")
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            while len(w) > width:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(w[:width])
                w = w[width:]
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    return lines
