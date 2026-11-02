import users
from users import get_user


def report_line(uid):
    u = get_user(uid)
    return f"{u['id']}: {u['name']} <{u['email']}>"


def report_all(ids):
    return [report_line(i) for i in ids] + [users.get_user(ids[0])["name"].upper()] if ids else []
