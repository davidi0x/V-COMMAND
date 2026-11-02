def render(summary):
    rows = [(k, str(v["count"]), f"{v['sum']:.2f}", "-" if v["avg"] is None else f"{v['avg']:.2f}")
            for k, v in sorted(summary.items(), key=lambda kv: (-kv[1]["sum"], kv[0]))]
    header = ("key", "count", "sum", "avg")
    widths = [max(len(header[c]), *(len(r[c]) for r in rows)) if rows else len(header[c]) for c in range(4)]
    widths[0] = max(widths[0], 3)

    def line(cells):
        return (cells[0].ljust(widths[0]) + "  " + "  ".join(cells[c].rjust(widths[c]) for c in range(1, 4))).rstrip()

    return "\n".join([line(header)] + [line(r) for r in rows])
