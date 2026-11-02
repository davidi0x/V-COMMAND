import json
import os
import tempfile
import unittest

import app
from config import load_config
from defaults import DEFAULTS
from errors import ConfigError


class T(unittest.TestCase):
    def test_defaults_only_and_not_aliased(self):
        cfg = load_config(env={})
        self.assertEqual(cfg, DEFAULTS)
        cfg["db"]["port"] = 1
        self.assertEqual(DEFAULTS["db"]["port"], 5432)  # defaults are never mutated

    def test_file_deep_merge(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            with open(p, "w") as f:
                json.dump({"db": {"host": "db.internal"}, "debug": True}, f)
            cfg = load_config(p, env={})
        self.assertEqual(cfg["db"], {"host": "db.internal", "port": 5432, "name": "app"})
        self.assertTrue(cfg["debug"])
        self.assertEqual(cfg["cache"], DEFAULTS["cache"])

    def test_env_overrides_file_and_coerces(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            with open(p, "w") as f:
                json.dump({"db": {"port": 6000}}, f)
            cfg = load_config(p, env={"APP_DB__PORT": "5433", "app_cache__enabled": "no", "APP_CACHE__TTL": "1.25",
                                      "APP_DEBUG": "Yes", "OTHER": "x"})
        self.assertEqual(cfg["db"]["port"], 5433)
        self.assertIs(cfg["cache"]["enabled"], False)
        self.assertEqual(cfg["cache"]["ttl"], 1.25)
        self.assertIs(cfg["debug"], True)

    def test_bad_values_raise(self):
        for env in ({"APP_DB__PORT": "abc"}, {"APP_DEBUG": "maybe"}, {"APP_DB__NOPE": "1"}, {"APP_NOPE": "1"}):
            with self.assertRaises(ConfigError, msg=str(env)):
                load_config(env=env)

    def test_default_env_is_os_environ(self):
        os.environ["APP_DB__NAME"] = "fromenv"
        self.addCleanup(os.environ.pop, "APP_DB__NAME")
        self.assertEqual(load_config()["db"]["name"], "fromenv")

    def test_app_dsn_uses_loaded_config(self):
        self.assertEqual(app.dsn({"db": {"host": "h", "port": 1, "name": "n"}}), "h:1/n")
        os.environ["APP_DB__HOST"] = "envhost"
        self.addCleanup(os.environ.pop, "APP_DB__HOST")
        self.assertEqual(app.dsn(), "envhost:5432/app")


if __name__ == "__main__":
    unittest.main()
