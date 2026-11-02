def render(invoice):
    lines = []
    for i in invoice.items:
        line = f"{i.name} x{i.qty} @ {i.price:.2f} = {i.subtotal():.2f}"
        if i.tax_rate > 0:
            line += f" + tax {i.tax():.2f}"
        lines.append(line)
    if invoice.tax_total() > 0:
        lines.append(f"TAX {invoice.tax_total():.2f}")
    lines.append(f"TOTAL {invoice.total():.2f}")
    return "\n".join(lines)
