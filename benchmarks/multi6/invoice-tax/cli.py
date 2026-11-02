from invoice import Invoice
from models import Item
from render import render


def parse_item(arg):
    name, price, qty = arg.split(":")
    return Item(name, float(price), int(qty))


def main(argv):
    print(render(Invoice([parse_item(a) for a in argv])))
    return 0
