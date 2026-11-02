from users import get_user as lookup


def greeting(uid):
    return f"Hello {lookup(uid)['name']}!"
