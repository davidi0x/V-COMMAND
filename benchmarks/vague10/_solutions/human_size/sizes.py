from errors import ValidationError


def human_size(n):
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValidationError("n must be a non-negative int")
    if n < 1024:
        return f"{n} B"
    size = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
