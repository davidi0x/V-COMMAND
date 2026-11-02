import warnings

_USERS = {1: {"id": 1, "name": "Ada", "email": "ada@example.com"}, 2: {"id": 2, "name": "Linus", "email": "linus@example.com"}}


def get_user(uid):
    if uid not in _USERS:
        raise KeyError(f"no user {uid}")
    return dict(_USERS[uid])


def fetch_user(uid):
    warnings.warn("fetch_user() is deprecated, use get_user()", DeprecationWarning, stacklevel=2)
    return get_user(uid)
