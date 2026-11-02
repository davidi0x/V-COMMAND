import unittest

from audit import AuditLog
from bus import EventBus
from orders import OrderService


class T(unittest.TestCase):
    def test_priority_then_subscription_order(self):
        bus, seen = EventBus(), []
        bus.subscribe("t", lambda p: seen.append("low"), priority=0)
        bus.subscribe("t", lambda p: seen.append("high"), priority=5)
        bus.subscribe("t", lambda p: seen.append("low2"), priority=0)
        bus.publish("t", 1)
        self.assertEqual(seen, ["high", "low", "low2"])

    def test_wildcard_and_exact(self):
        bus, seen = EventBus(), []
        bus.subscribe("order.*", lambda p: seen.append(("star", p)))
        bus.subscribe("order.placed", lambda p: seen.append(("exact", p)))
        bus.publish("order.placed", 1)
        bus.publish("order.shipped", 2)
        bus.publish("orders.other", 3)
        self.assertEqual(seen, [("star", 1), ("exact", 1), ("star", 2)])

    def test_with_topic(self):
        bus, seen = EventBus(), []
        bus.subscribe("a.*", lambda t, p: seen.append((t, p)), with_topic=True)
        bus.subscribe("a.b", lambda p: seen.append(p))
        bus.publish("a.b", 1)
        self.assertEqual(seen, [("a.b", 1), 1])

    def test_error_isolation(self):
        bus, seen = EventBus(), []

        def boom(p):
            raise RuntimeError("x")

        bus.subscribe("t", boom, priority=9)
        bus.subscribe("t", lambda p: seen.append(p))
        errors = bus.publish("t", 7)
        self.assertEqual(seen, [7])
        self.assertEqual([type(e) for e in errors], [RuntimeError])

    def test_publish_without_subscribers(self):
        self.assertEqual(EventBus().publish("nobody", None), [])

    def test_unsubscribe(self):
        bus, seen = EventBus(), []

        def h(p):
            seen.append(p)

        bus.subscribe("t", h)
        bus.unsubscribe("t", h)
        bus.publish("t", 1)
        self.assertEqual(seen, [])
        bus.unsubscribe("t", h)  # unknown handler: no error

    def test_handler_may_unsubscribe_while_publishing(self):
        bus, seen = EventBus(), []

        def once(p):
            seen.append("once")
            bus.unsubscribe("t", once)

        bus.subscribe("t", once)
        bus.subscribe("t", lambda p: seen.append("other"))
        bus.publish("t")
        bus.publish("t")
        self.assertEqual(seen, ["once", "other", "other"])

    def test_orders_publish_after_storing(self):
        bus = EventBus()
        svc = OrderService(bus)
        snapshot = {}
        bus.subscribe("order.placed", lambda o: snapshot.update(stored=o["id"] in svc.orders, order=o))
        oid = svc.place({"sku": "A1", "qty": 2})
        self.assertEqual(oid, 1)
        self.assertTrue(snapshot["stored"])
        self.assertEqual(snapshot["order"], {"sku": "A1", "qty": 2, "id": 1})

    def test_audit_records_all_order_events(self):
        bus = EventBus()
        audit = AuditLog()
        audit.attach(bus)
        svc = OrderService(bus)
        svc.place({"sku": "B2", "qty": 1})
        bus.publish("order.shipped", {"id": 1})
        bus.publish("user.created", {"id": 9})
        self.assertEqual(audit.entries, [("order.placed", {"sku": "B2", "qty": 1, "id": 1}), ("order.shipped", {"id": 1})])


if __name__ == "__main__":
    unittest.main()
