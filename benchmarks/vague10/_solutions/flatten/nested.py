from errors import ValidationError


def flatten(items, depth=None):
    if depth is not None and (isinstance(depth, bool) or not isinstance(depth, int) or depth < 0):
        raise ValidationError("depth must be None or an int >= 0")
    out = []

    def walk(seq, d):
        for x in seq:
            if isinstance(x, (list, tuple)) and (d is None or d > 0):
                walk(x, None if d is None else d - 1)
            else:
                out.append(x)

    walk(items, depth)
    return out
