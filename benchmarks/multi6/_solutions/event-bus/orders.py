class OrderService:
    def __init__(self, bus):
        self.bus = bus
        self.orders = {}
        self._next = 1

    def place(self, order):
        oid = self._next
        self._next += 1
        self.orders[oid] = dict(order, id=oid)
        self.bus.publish("order.placed", dict(self.orders[oid]))
        return oid
