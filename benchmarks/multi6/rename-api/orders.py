from users import fetch_user


def order_owner(order):
    return fetch_user(order["user_id"])["name"]
