from config import load_config


def dsn(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    db = cfg["db"]
    return f"{db['host']}:{db['port']}/{db['name']}"
