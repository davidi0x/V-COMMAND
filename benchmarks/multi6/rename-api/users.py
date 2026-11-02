_USERS = {1: {"id": 1, "name": "Ada", "email": "ada@example.com"}, 2: {"id": 2, "name": "Linus", "email": "linus@example.com"}}


def fetch_user(uid):
    if uid not in _USERS:
        raise KeyError(f"no user {uid}")
    return dict(_USERS[uid])
