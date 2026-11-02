def _records(text):
    """Split into records of fields; returns a list of (line_number, fields)."""
    records, fields, field = [], [], []
    in_quotes = False
    i, line, start_line, n = 0, 1, 1, len(text)
    pending = False  # something was read for the current record
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                if ch == "\n":
                    line += 1
                field.append(ch)
        elif ch == '"':
            in_quotes = True
            pending = True
        elif ch == ",":
            fields.append("".join(field))
            field = []
            pending = True
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if pending or field:
                fields.append("".join(field))
                records.append((start_line, fields))
            fields, field, pending = [], [], False
            line += 1
            start_line = line
        else:
            field.append(ch)
            pending = True
        i += 1
    if pending or field:
        fields.append("".join(field))
        records.append((start_line, fields))
    return records


def parse(text):
    records = _records(text)
    if not records:
        return []
    header = records[0][1]
    rows = []
    for line, fields in records[1:]:
        if len(fields) != len(header):
            raise ValueError(f"line {line}: expected {len(header)} fields, got {len(fields)}")
        rows.append(dict(zip(header, fields)))
    return rows
