import copy
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
