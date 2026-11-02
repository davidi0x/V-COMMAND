import users
from users import fetch_user


def report_line(uid):
    u = fetch_user(uid)
    return f"{u['id']}: {u['name']} <{u['email']}>"


def report_all(ids):
    return [report_line(i) for i in ids] + [users.fetch_user(ids[0])["name"].upper()] if ids else []
