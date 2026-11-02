def summarize(rows, key, value):
    out = {}
    for row in rows:
        entry = out.setdefault(row[key], {"count": 0, "sum": 0.0, "avg": None})
        raw = row[value].strip()
        if raw == "":
            continue
        try:
            number = float(raw)
        except ValueError as error:
            raise ValueError(f"not a number: {row[value]!r}") from error
        entry["count"] += 1
        entry["sum"] += number
    for entry in out.values():
        entry["sum"] = round(entry["sum"], 2)
        entry["avg"] = round(entry["sum"] / entry["count"], 2) if entry["count"] else None
    return out
