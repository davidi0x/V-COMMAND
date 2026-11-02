#!/usr/bin/env python3
"""Generate benchmarks/multi6: six multi-file Python tasks (3-4 files each, explicit goals).

Unlike vague10 the goal states the behavior; the difficulty is that a feature must be implemented *across
modules* (a field flowing through model, totals, renderer and CLI; a rename with a deprecation shim and every
caller; a cache with a clock; layered configuration; an event bus wired into two services; a CSV pipeline).
Every task has a reference solution in `_solutions/<id>/`; CI checks that it fails as shipped and passes with it.

Run: python scripts/gen_multi_suite.py   (rewrites benchmarks/multi6)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "benchmarks" / "multi6"

TASKS: list[dict] = []


def task(**kw):
    TASKS.append(kw)


# ------------------------------------------------------------------------------------------------ 1 invoice tax
task(
    id="invoice-tax", gate="test_invoice.py",
    goal=("Add per-item tax to the invoice code. `Item` gets `tax_rate` (default 0.0, e.g. 0.2 = 20%) with methods "
          "`tax()` (rounded to 2 decimals) and `gross()` (subtotal + tax); `Invoice.total()` is the sum of gross "
          "amounts and `Invoice.tax_total()` the sum of taxes; `render()` appends ` + tax 0.40` to an item line only "
          "when its rate is above 0 and prints a `TAX x.xx` line before `TOTAL` only when the tax total is above 0; "
          "the CLI accepts an optional 4th field `name:price:qty:rate`. Items without tax must behave exactly as before."),
    files={
        "models.py": '''from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    price: float
    qty: int = 1

    def subtotal(self):
        return round(self.price * self.qty, 2)
''',
        "invoice.py": '''class Invoice:
    def __init__(self, items):
        self.items = list(items)

    def total(self):
        return round(sum(i.subtotal() for i in self.items), 2)
''',
        "render.py": '''def render(invoice):
    lines = [f"{i.name} x{i.qty} @ {i.price:.2f} = {i.subtotal():.2f}" for i in invoice.items]
    lines.append(f"TOTAL {invoice.total():.2f}")
    return "\\n".join(lines)
''',
        "cli.py": '''from invoice import Invoice
from models import Item
from render import render


def parse_item(arg):
    name, price, qty = arg.split(":")
    return Item(name, float(price), int(qty))


def main(argv):
    print(render(Invoice([parse_item(a) for a in argv])))
    return 0
''',
        "test_invoice.py": '''import io
import unittest
from contextlib import redirect_stdout

from cli import main, parse_item
from invoice import Invoice
from models import Item
from render import render


class T(unittest.TestCase):
    def test_default_rate_is_zero(self):
        it = Item("pen", 2.0, 3)
        self.assertEqual((it.tax_rate, it.tax(), it.gross()), (0.0, 0.0, 6.0))

    def test_tax_and_gross(self):
        it = Item("lamp", 10.0, 2, 0.2)
        self.assertEqual((it.subtotal(), it.tax(), it.gross()), (20.0, 4.0, 24.0))

    def test_rounding(self):
        it = Item("x", 0.33, 3, 0.07)
        self.assertEqual((it.subtotal(), it.tax(), it.gross()), (0.99, 0.07, 1.06))

    def test_invoice_totals(self):
        inv = Invoice([Item("a", 10.0, 1, 0.1), Item("b", 5.0, 2)])
        self.assertEqual((inv.tax_total(), inv.total()), (1.0, 21.0))

    def test_render_untaxed_unchanged(self):
        inv = Invoice([Item("pen", 2.0, 3)])
        self.assertEqual(render(inv), "pen x3 @ 2.00 = 6.00\\nTOTAL 6.00")

    def test_render_taxed(self):
        inv = Invoice([Item("lamp", 10.0, 2, 0.2), Item("pen", 2.0, 1)])
        self.assertEqual(render(inv), "lamp x2 @ 10.00 = 20.00 + tax 4.00\\npen x1 @ 2.00 = 2.00\\nTAX 4.00\\nTOTAL 26.00")

    def test_cli_optional_rate(self):
        self.assertEqual(parse_item("a:1.5:2"), Item("a", 1.5, 2, 0.0))
        self.assertEqual(parse_item("a:1.5:2:0.25"), Item("a", 1.5, 2, 0.25))
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["lamp:10:2:0.2", "pen:2:1"])
        self.assertTrue(buf.getvalue().strip().endswith("TAX 4.00\\nTOTAL 26.00"))


if __name__ == "__main__":
    unittest.main()
''',
    },
    solution={
        "models.py": '''from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    price: float
    qty: int = 1
    tax_rate: float = 0.0

    def subtotal(self):
        return round(self.price * self.qty, 2)

    def tax(self):
        return round(self.subtotal() * self.tax_rate, 2)

    def gross(self):
        return round(self.subtotal() + self.tax(), 2)
''',
        "invoice.py": '''class Invoice:
    def __init__(self, items):
        self.items = list(items)

    def total(self):
        return round(sum(i.gross() for i in self.items), 2)

    def tax_total(self):
        return round(sum(i.tax() for i in self.items), 2)
''',
        "render.py": '''def render(invoice):
    lines = []
    for i in invoice.items:
        line = f"{i.name} x{i.qty} @ {i.price:.2f} = {i.subtotal():.2f}"
        if i.tax_rate > 0:
            line += f" + tax {i.tax():.2f}"
        lines.append(line)
    if invoice.tax_total() > 0:
        lines.append(f"TAX {invoice.tax_total():.2f}")
    lines.append(f"TOTAL {invoice.total():.2f}")
    return "\\n".join(lines)
''',
        "cli.py": '''from invoice import Invoice
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
''',
    },
)

# ------------------------------------------------------------------------------------------------ 2 rename api
task(
    id="rename-api", gate="test_rename.py",
    goal=("Rename `fetch_user` to `get_user` in users.py and update every caller in the package. Keep `fetch_user` "
          "as a deprecated alias that emits a `DeprecationWarning` (message must mention `get_user`) and returns "
          "the same result. No code in the package other than that alias may trigger the warning."),
    files={
        "users.py": '''_USERS = {1: {"id": 1, "name": "Ada", "email": "ada@example.com"}, 2: {"id": 2, "name": "Linus", "email": "linus@example.com"}}


def fetch_user(uid):
    if uid not in _USERS:
        raise KeyError(f"no user {uid}")
    return dict(_USERS[uid])
''',
        "orders.py": '''from users import fetch_user


def order_owner(order):
    return fetch_user(order["user_id"])["name"]
''',
        "reports.py": '''import users
from users import fetch_user


def report_line(uid):
    u = fetch_user(uid)
    return f"{u['id']}: {u['name']} <{u['email']}>"


def report_all(ids):
    return [report_line(i) for i in ids] + [users.fetch_user(ids[0])["name"].upper()] if ids else []
''',
        "notify.py": '''from users import fetch_user as lookup


def greeting(uid):
    return f"Hello {lookup(uid)['name']}!"
''',
        "test_rename.py": '''import unittest
import warnings

import notify
import orders
import reports
import users


class T(unittest.TestCase):
    def test_get_user(self):
        self.assertEqual(users.get_user(1)["name"], "Ada")
        with self.assertRaises(KeyError):
            users.get_user(99)

    def test_deprecated_alias(self):
        with self.assertWarns(DeprecationWarning) as cm:
            u = users.fetch_user(2)
        self.assertEqual(u, users.get_user(2))
        self.assertIn("get_user", str(cm.warning))

    def test_alias_still_raises_keyerror(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with self.assertRaises(KeyError):
                users.fetch_user(99)

    def test_callers_do_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertEqual(orders.order_owner({"user_id": 1}), "Ada")
            self.assertEqual(reports.report_line(2), "2: Linus <linus@example.com>")
            self.assertEqual(reports.report_all([1, 2]), ["1: Ada <ada@example.com>", "2: Linus <linus@example.com>", "ADA"])
            self.assertEqual(notify.greeting(1), "Hello Ada!")

    def test_no_old_name_left_in_callers(self):
        import pathlib
        for f in ("orders.py", "reports.py", "notify.py"):
            self.assertNotIn("fetch_user", pathlib.Path(f).read_text(), f)


if __name__ == "__main__":
    unittest.main()
''',
    },
    solution={
        "users.py": '''import warnings

_USERS = {1: {"id": 1, "name": "Ada", "email": "ada@example.com"}, 2: {"id": 2, "name": "Linus", "email": "linus@example.com"}}


def get_user(uid):
    if uid not in _USERS:
        raise KeyError(f"no user {uid}")
    return dict(_USERS[uid])


def fetch_user(uid):
    warnings.warn("fetch_user() is deprecated, use get_user()", DeprecationWarning, stacklevel=2)
    return get_user(uid)
''',
        "orders.py": '''from users import get_user


def order_owner(order):
    return get_user(order["user_id"])["name"]
''',
        "reports.py": '''import users
from users import get_user


def report_line(uid):
    u = get_user(uid)
    return f"{u['id']}: {u['name']} <{u['email']}>"


def report_all(ids):
    return [report_line(i) for i in ids] + [users.get_user(ids[0])["name"].upper()] if ids else []
''',
        "notify.py": '''from users import get_user as lookup


def greeting(uid):
    return f"Hello {lookup(uid)['name']}!"
''',
    },
)

# ------------------------------------------------------------------------------------------------ 3 cache
task(
    id="ttl-cache", gate="test_cache.py",
    goal=("Add a TTL cache decorator `cached(ttl)` to cache.py and use it in services.py. Keys are the call "
          "arguments (positional and keyword calls with the same values share an entry); entries expire after `ttl` "
          "seconds measured by a replaceable clock (`cache.set_clock(fn)`, default `time.monotonic`); exceptions are "
          "never cached; `cache.clear_cache()` empties every cache. Apply `@cached(60)` to `services.get_price` and "
          "`@cached(5)` to `services.get_stock`; the functions must keep their names and docstrings."),
    files={
        "backend.py": '''CALLS = {"price": 0, "stock": 0}
PRICES = {"A1": 9.99, "B2": 24.5}
STOCK = {"A1": 3, "B2": 0}


def load_price(sku):
    CALLS["price"] += 1
    return PRICES[sku]


def load_stock(sku):
    CALLS["stock"] += 1
    return STOCK[sku]
''',
        "cache.py": '''import time


def set_clock(fn):
    raise NotImplementedError


def clear_cache():
    raise NotImplementedError


def cached(ttl):
    raise NotImplementedError
''',
        "services.py": '''import backend


def get_price(sku):
    """Current price."""
    return backend.load_price(sku)


def get_stock(sku):
    """Units in stock."""
    return backend.load_stock(sku)
''',
        "test_cache.py": '''import unittest

import backend
import cache
import services


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class T(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        cache.set_clock(self.clock)
        cache.clear_cache()
        backend.CALLS.update(price=0, stock=0)

    def test_hit_and_miss(self):
        self.assertEqual(services.get_price("A1"), 9.99)
        self.assertEqual(services.get_price("A1"), 9.99)
        self.assertEqual(backend.CALLS["price"], 1)
        services.get_price("B2")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_args_and_kwargs_share_entry(self):
        services.get_price("A1")
        services.get_price(sku="A1")
        self.assertEqual(backend.CALLS["price"], 1)

    def test_expiry_per_function(self):
        services.get_price("A1")
        services.get_stock("A1")
        self.clock.now += 6
        services.get_price("A1")
        services.get_stock("A1")
        self.assertEqual((backend.CALLS["price"], backend.CALLS["stock"]), (1, 2))  # stock ttl 5, price ttl 60
        self.clock.now += 60
        services.get_price("A1")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_exceptions_not_cached(self):
        for _ in range(2):
            with self.assertRaises(KeyError):
                services.get_price("ZZ")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_clear_cache(self):
        services.get_price("A1")
        cache.clear_cache()
        services.get_price("A1")
        self.assertEqual(backend.CALLS["price"], 2)

    def test_metadata_preserved(self):
        self.assertEqual(services.get_price.__name__, "get_price")
        self.assertEqual(services.get_stock.__doc__, "Units in stock.")

    def test_falsy_values_are_cached(self):
        self.assertEqual(services.get_stock("B2"), 0)
        self.assertEqual(services.get_stock("B2"), 0)
        self.assertEqual(backend.CALLS["stock"], 1)


if __name__ == "__main__":
    unittest.main()
''',
    },
    solution={
        "cache.py": '''import functools
import inspect
import time

_clock = time.monotonic
_stores = []


def set_clock(fn):
    global _clock
    _clock = fn


def clear_cache():
    for store in _stores:
        store.clear()


def cached(ttl):
    def deco(fn):
        store = {}
        _stores.append(store)
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            key = tuple(bound.arguments.items())
            now = _clock()
            hit = store.get(key)
            if hit is not None and now - hit[0] < ttl:
                return hit[1]
            value = fn(*args, **kwargs)
            store[key] = (now, value)
            return value

        return wrapper

    return deco
''',
        "services.py": '''import backend
from cache import cached


@cached(60)
def get_price(sku):
    """Current price."""
    return backend.load_price(sku)


@cached(5)
def get_stock(sku):
    """Units in stock."""
    return backend.load_stock(sku)
''',
    },
)

# ------------------------------------------------------------------------------------------------ 4 config layers
task(
    id="config-layers", gate="test_config.py",
    goal=("Implement `load_config(path=None, env=None)` in config.py and make app.py use it. Result = DEFAULTS, "
          "deep-merged with the JSON file at `path` (if given), then with environment variables named "
          "`APP_<SECTION>__<KEY>` (case-insensitive, `__` separates nesting, e.g. `APP_DB__PORT=5433`), where env "
          "is a dict (default `os.environ`). Env values are coerced to the type of the default (int, float, bool: "
          "true/false/1/0/yes/no, str); a value that cannot be coerced, or an `APP_` variable that matches no "
          "default key, raises `errors.ConfigError`. `app.dsn(cfg=None)` must build `host:port/name` from the "
          "loaded configuration (loading it when `cfg` is None)."),
    files={
        "errors.py": '''class ConfigError(Exception):
    pass
''',
        "defaults.py": '''DEFAULTS = {
    "debug": False,
    "db": {"host": "localhost", "port": 5432, "name": "app"},
    "cache": {"ttl": 30.5, "enabled": True},
}
''',
        "config.py": '''def load_config(path=None, env=None):
    raise NotImplementedError
''',
        "app.py": '''from defaults import DEFAULTS


def dsn(cfg=None):
    db = DEFAULTS["db"]
    return f"{db['host']}:{db['port']}/{db['name']}"
''',
        "test_config.py": '''import json
import os
import tempfile
import unittest

import app
from config import load_config
from defaults import DEFAULTS
from errors import ConfigError


class T(unittest.TestCase):
    def test_defaults_only_and_not_aliased(self):
        cfg = load_config(env={})
        self.assertEqual(cfg, DEFAULTS)
        cfg["db"]["port"] = 1
        self.assertEqual(DEFAULTS["db"]["port"], 5432)  # defaults are never mutated

    def test_file_deep_merge(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            with open(p, "w") as f:
                json.dump({"db": {"host": "db.internal"}, "debug": True}, f)
            cfg = load_config(p, env={})
        self.assertEqual(cfg["db"], {"host": "db.internal", "port": 5432, "name": "app"})
        self.assertTrue(cfg["debug"])
        self.assertEqual(cfg["cache"], DEFAULTS["cache"])

    def test_env_overrides_file_and_coerces(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            with open(p, "w") as f:
                json.dump({"db": {"port": 6000}}, f)
            cfg = load_config(p, env={"APP_DB__PORT": "5433", "app_cache__enabled": "no", "APP_CACHE__TTL": "1.25",
                                      "APP_DEBUG": "Yes", "OTHER": "x"})
        self.assertEqual(cfg["db"]["port"], 5433)
        self.assertIs(cfg["cache"]["enabled"], False)
        self.assertEqual(cfg["cache"]["ttl"], 1.25)
        self.assertIs(cfg["debug"], True)

    def test_bad_values_raise(self):
        for env in ({"APP_DB__PORT": "abc"}, {"APP_DEBUG": "maybe"}, {"APP_DB__NOPE": "1"}, {"APP_NOPE": "1"}):
            with self.assertRaises(ConfigError, msg=str(env)):
                load_config(env=env)

    def test_default_env_is_os_environ(self):
        os.environ["APP_DB__NAME"] = "fromenv"
        self.addCleanup(os.environ.pop, "APP_DB__NAME")
        self.assertEqual(load_config()["db"]["name"], "fromenv")

    def test_app_dsn_uses_loaded_config(self):
        self.assertEqual(app.dsn({"db": {"host": "h", "port": 1, "name": "n"}}), "h:1/n")
        os.environ["APP_DB__HOST"] = "envhost"
        self.addCleanup(os.environ.pop, "APP_DB__HOST")
        self.assertEqual(app.dsn(), "envhost:5432/app")


if __name__ == "__main__":
    unittest.main()
''',
    },
    solution={
        "config.py": '''import copy
import json
import os

from defaults import DEFAULTS
from errors import ConfigError

_TRUE, _FALSE = {"true", "1", "yes"}, {"false", "0", "no"}


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def _coerce(raw, default, name):
    try:
        if isinstance(default, bool):
            low = raw.strip().lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
            raise ValueError(raw)
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        return raw
    except ValueError as error:
        raise ConfigError(f"{name}: cannot read {raw!r} as {type(default).__name__}") from error


def load_config(path=None, env=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path is not None:
        with open(path, encoding="utf-8") as f:
            _merge(cfg, json.load(f))
    env = os.environ if env is None else env
    for name, raw in env.items():
        if not name.upper().startswith("APP_"):
            continue
        keys = name[4:].lower().split("__")
        node, defaults = cfg, DEFAULTS
        for k in keys[:-1]:
            if not isinstance(defaults.get(k), dict):
                raise ConfigError(f"{name}: unknown setting")
            node, defaults = node[k], defaults[k]
        last = keys[-1]
        if last not in defaults or isinstance(defaults[last], dict):
            raise ConfigError(f"{name}: unknown setting")
        node[last] = _coerce(raw, defaults[last], name)
    return cfg
''',
        "app.py": '''from config import load_config


def dsn(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    db = cfg["db"]
    return f"{db['host']}:{db['port']}/{db['name']}"
''',
    },
)

# ------------------------------------------------------------------------------------------------ 5 event bus
task(
    id="event-bus", gate="test_bus.py",
    goal=("Implement `EventBus` in bus.py: `subscribe(topic, handler, priority=0, with_topic=False)` (topic may end in "
          "`.*` to match every topic with that prefix, e.g. `order.*`), `unsubscribe(topic, handler)`, and "
          "`publish(topic, payload)` which calls matching handlers highest priority first (equal priority: "
          "subscription order) as `handler(payload)` — or `handler(topic, payload)` when subscribed with "
          "`with_topic=True` — and returns the list of exceptions the handlers raised; one failing handler must not "
          "stop the others, and a handler may unsubscribe itself while being called. Then make "
          "`OrderService.place(order)` publish `order.placed` with a copy of the stored order (after storing it) and "
          "give `AuditLog` an `attach(bus)` method that records `(topic, payload)` for every `order.*` event."),
    files={
        "bus.py": '''class EventBus:
    def subscribe(self, topic, handler, priority=0):
        raise NotImplementedError

    def unsubscribe(self, topic, handler):
        raise NotImplementedError

    def publish(self, topic, payload=None):
        raise NotImplementedError
''',
        "orders.py": '''class OrderService:
    def __init__(self, bus):
        self.bus = bus
        self.orders = {}
        self._next = 1

    def place(self, order):
        oid = self._next
        self._next += 1
        self.orders[oid] = dict(order, id=oid)
        return oid
''',
        "audit.py": '''class AuditLog:
    def __init__(self):
        self.entries = []
''',
        "test_bus.py": '''import unittest

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
''',
    },
    solution={
        "bus.py": '''class EventBus:
    def __init__(self):
        self._subs = []  # (topic, handler, priority, seq, with_topic)
        self._seq = 0

    def subscribe(self, topic, handler, priority=0, with_topic=False):
        self._seq += 1
        self._subs.append((topic, handler, priority, self._seq, with_topic))

    def unsubscribe(self, topic, handler):
        self._subs = [s for s in self._subs if not (s[0] == topic and s[1] == handler)]

    @staticmethod
    def _matches(pattern, topic):
        if pattern.endswith(".*"):
            return topic.startswith(pattern[:-1])
        return pattern == topic

    def publish(self, topic, payload=None):
        matching = [s for s in self._subs if self._matches(s[0], topic)]
        matching.sort(key=lambda s: (-s[2], s[3]))
        errors = []
        for _, handler, _, _, with_topic in matching:
            try:
                handler(topic, payload) if with_topic else handler(payload)
            except Exception as error:  # noqa: BLE001 - isolation is the point
                errors.append(error)
        return errors
''',
        "orders.py": '''class OrderService:
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
''',
        "audit.py": '''class AuditLog:
    def __init__(self):
        self.entries = []

    def attach(self, bus):
        bus.subscribe("order.*", lambda topic, payload: self.entries.append((topic, payload)), with_topic=True)
''',
    },
)

# ------------------------------------------------------------------------------------------------ 6 csv report
task(
    id="csv-report", gate="test_report.py",
    goal=("Implement the CSV pipeline across three modules. parser.py `parse(text)` -> list of dicts keyed by the "
          "header row, supporting quoted fields with commas, doubled quotes (`\"\"`) and newlines inside quotes, "
          "CRLF or LF line ends, and ignoring a trailing blank line; a row with the wrong number of fields raises "
          "`ValueError` naming the 1-based line. stats.py `summarize(rows, key, value)` -> dict mapping each key to "
          "`{\"count\": n, \"sum\": s, \"avg\": a}` over the numeric `value` column, where blank values are skipped "
          "(not counted) and a non-numeric value raises `ValueError`; avg is rounded to 2 decimals and is `None` "
          "when nothing was counted. report.py `render(summary)` -> text table with a header `key  count  sum  avg`, "
          "rows sorted by sum descending then key ascending, numbers right-aligned in columns sized to the widest "
          "cell, sums with 2 decimals, avg `-` when None."),
    files={
        "parser.py": '''def parse(text):
    raise NotImplementedError
''',
        "stats.py": '''def summarize(rows, key, value):
    raise NotImplementedError
''',
        "report.py": '''def render(summary):
    raise NotImplementedError
''',
        "test_report.py": '''import unittest

from parser import parse
from report import render
from stats import summarize

CSV = "region,item,amount\\r\\nnorth,\\"widget, large\\",10.5\\r\\nsouth,gadget,4\\r\\nnorth,gizmo,\\r\\nnorth,\\"say \\"\\"hi\\"\\"\\",2.25\\r\\n"


class T(unittest.TestCase):
    def test_parse_quotes_and_crlf(self):
        rows = parse(CSV)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], {"region": "north", "item": "widget, large", "amount": "10.5"})
        self.assertEqual(rows[3]["item"], 'say "hi"')
        self.assertEqual(rows[2]["amount"], "")

    def test_parse_newline_in_quotes_and_lf(self):
        rows = parse('a,b\\n1,"x\\ny"\\n')
        self.assertEqual(rows, [{"a": "1", "b": "x\\ny"}])

    def test_parse_no_trailing_newline_and_empty(self):
        self.assertEqual(parse("a,b\\n1,2"), [{"a": "1", "b": "2"}])
        self.assertEqual(parse("a,b\\n"), [])
        self.assertEqual(parse(""), [])

    def test_parse_bad_row_names_the_line(self):
        with self.assertRaises(ValueError) as cm:
            parse("a,b\\n1,2\\n3\\n")
        self.assertIn("3", str(cm.exception))

    def test_summarize(self):
        s = summarize(parse(CSV), "region", "amount")
        self.assertEqual(s["north"], {"count": 2, "sum": 12.75, "avg": 6.38})
        self.assertEqual(s["south"], {"count": 1, "sum": 4.0, "avg": 4.0})

    def test_summarize_blank_only_and_bad_value(self):
        s = summarize([{"k": "a", "v": ""}], "k", "v")
        self.assertEqual(s["a"], {"count": 0, "sum": 0.0, "avg": None})
        with self.assertRaises(ValueError):
            summarize([{"k": "a", "v": "x"}], "k", "v")

    def test_render(self):
        s = summarize(parse(CSV), "region", "amount")
        self.assertEqual(render(s), "key    count    sum   avg\\nnorth      2  12.75  6.38\\nsouth      1   4.00  4.00")

    def test_render_order_and_dash(self):
        s = {"b": {"count": 1, "sum": 5.0, "avg": 5.0}, "a": {"count": 1, "sum": 5.0, "avg": 5.0},
             "z": {"count": 0, "sum": 0.0, "avg": None}}
        lines = render(s).splitlines()
        self.assertEqual([l.split()[0] for l in lines[1:]], ["a", "b", "z"])
        self.assertTrue(lines[3].rstrip().endswith("-"))

    def test_pipeline(self):
        out = render(summarize(parse("team,pts\\nred,3\\nblue,9\\nred,4\\n"), "team", "pts"))
        self.assertEqual(out.splitlines()[1].split(), ["blue", "1", "9.00", "9.00"])


if __name__ == "__main__":
    unittest.main()
''',
    },
    solution={
        "parser.py": '''def _records(text):
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
                if ch == "\\n":
                    line += 1
                field.append(ch)
        elif ch == '"':
            in_quotes = True
            pending = True
        elif ch == ",":
            fields.append("".join(field))
            field = []
            pending = True
        elif ch in "\\r\\n":
            if ch == "\\r" and i + 1 < n and text[i + 1] == "\\n":
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
''',
        "stats.py": '''def summarize(rows, key, value):
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
''',
        "report.py": '''def render(summary):
    rows = [(k, str(v["count"]), f"{v['sum']:.2f}", "-" if v["avg"] is None else f"{v['avg']:.2f}")
            for k, v in sorted(summary.items(), key=lambda kv: (-kv[1]["sum"], kv[0]))]
    header = ("key", "count", "sum", "avg")
    widths = [max(len(header[c]), *(len(r[c]) for r in rows)) if rows else len(header[c]) for c in range(4)]
    widths[0] = max(widths[0], 3)

    def line(cells):
        return (cells[0].ljust(widths[0]) + "  " + "  ".join(cells[c].rjust(widths[c]) for c in range(1, 4))).rstrip()

    return "\\n".join([line(header)] + [line(r) for r in rows])
''',
    },
)


def build(out: Path = OUT) -> None:
    if out.exists():
        shutil.rmtree(out)
    tasks = []
    for t in TASKS:
        d = out / t["id"]
        for name, body in t["files"].items():
            (d / name).parent.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(body, encoding="utf-8")
        sol = out / "_solutions" / t["id"]
        for name, body in t["solution"].items():
            sol.mkdir(parents=True, exist_ok=True)
            (sol / name).write_text(body, encoding="utf-8")
        tasks.append({"id": t["id"], "dir": t["id"], "goal": t["goal"], "focus": [],
                      "gates": [["python", "-B", t["gate"]]]})
    (out / "suite.json").write_text(json.dumps({
        "name": "multi6",
        "description": ("Six multi-file Python tasks with explicit goals (3-4 files each): a field through model, totals, "
                        "renderer and CLI; a rename with a deprecation shim and all callers; a TTL cache with a clock; "
                        "layered configuration; an event bus wired into two services; a three-module CSV pipeline."),
        "tasks": tasks}, indent=2) + "\n", encoding="utf-8")
    (out / "README.md").write_text("# multi6\n\nSix multi-file Python tasks. Regenerate: `python scripts/gen_multi_suite.py`.\n"
                                   "`_solutions/<id>/` holds the reference solution files (CI: each task fails as shipped, "
                                   "passes with its solution).\n", encoding="utf-8")


if __name__ == "__main__":
    build()
    print(f"wrote {OUT}")
