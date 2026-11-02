from errors import ValidationError


def merge_intervals(intervals):
    items = []
    for start, end in intervals:
        if start > end:
            raise ValidationError(f"invalid interval ({start}, {end})")
        items.append((start, end))
    items.sort()
    merged = []
    for start, end in items:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
