from invoice import Invoice
from models import Item
from render import render


def parse_item(arg):
    parts = arg.split(":")
    name, price, qty = parts[0], float(parts[1]), int(parts[2])
    rate = float(parts[3]) if len(parts) > 3 else 0.0
    return Item(name, price, qty, rate)


def main(argv):
    print(render(Invoice([parse_item(a) for a in argv])))
    return 0
