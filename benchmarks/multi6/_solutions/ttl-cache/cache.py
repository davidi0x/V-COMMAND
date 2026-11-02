import functools
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
