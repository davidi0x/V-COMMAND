from defaults import DEFAULTS


def dsn(cfg=None):
    db = DEFAULTS["db"]
    return f"{db['host']}:{db['port']}/{db['name']}"
