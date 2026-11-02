from errors import ValidationError


def chunk(items, size):
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValidationError("size must be an int >= 1")
    data = tuple(items)
    return [data[i:i + size] for i in range(0, len(data), size)]
