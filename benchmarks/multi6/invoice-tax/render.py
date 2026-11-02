def render(invoice):
    lines = [f"{i.name} x{i.qty} @ {i.price:.2f} = {i.subtotal():.2f}" for i in invoice.items]
    lines.append(f"TOTAL {invoice.total():.2f}")
    return "\n".join(lines)
