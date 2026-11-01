from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest

from vcommand.core import init_project, load_config, save_config, list_evidence, parse_cost
from vcommand.state import start_task
from vcommand.adapters import run_agents, open_circuits, load_health, provider_failure_reason, agent_templates

# Prints a Claude-style JSON result with a provider-reported cost, changes nothing.
PAID = "import json; print(json.dumps({'result': 'did ' + 'some work', 'total_cost_usd': 0.02}))"
# Provider down: exits 1 without touching any file (auth / quota / outage).
DOWN = "import sys; sys.exit(1)"
GOOD = "import pathlib; pathlib.Path('fixed.txt').write_text('ok')"
GATE = [sys.executable, "-c", "import pathlib, sys; sys.exit(0 if pathlib.Path('fixed.txt').exists() else 1)"]


class Stage3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_project(self.root)
        cfg = load_config(self.root)
        cfg["checks"] = [GATE]
        cfg["agents"] = {
            "paid": {"argv": [sys.executable, "-c", PAID, "{prompt}"], "cost": "claude-json"},
            "down": [sys.executable, "-c", DOWN, "{prompt}"],
            "good": [sys.executable, "-c", GOOD, "{prompt}"],
        }
        save_config(self.root, cfg)
        start_task(self.root, "Create fixed.txt")

    def agents(self, *names, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            out = io.StringIO()
            code = run_agents(self.root, list(names), out=out, **kw)
        return code, out.getvalue()

    def test_cost_recorded_from_provider_receipt_output_not_stored(self):
        self.agents("paid", attempts=1)
        run = list_evidence(self.root)[-1]
        self.assertEqual(run["cost"], {"currency": "USD", "amount": 0.02, "source": "claude-code total_cost_usd"})
        self.assertNotIn("did some work", json.dumps(run))
        self.assertEqual(run["task_id"], json.loads((self.root / ".vcommand/task.json").read_text())["id"])

    def test_unparseable_output_keeps_cost_unknown(self):
        cost = parse_cost("claude-json", b"not json at all", io.StringIO())
        self.assertIsNone(cost["amount"])

    def test_budget_stops_before_next_attempt(self):
        code, out = self.agents("paid", attempts=5, budget_usd=0.03)
        self.assertEqual(code, 1)
        self.assertEqual(len(list_evidence(self.root)), 2)  # 0.02, 0.04 >= 0.03 -> stop
        self.assertIn("BUDGET     stopped: $0.0400 of $0.0300", out)

    def test_budget_from_config(self):
        cfg = load_config(self.root)
        cfg["budget"] = {"max_usd_per_task": 0.01}
        save_config(self.root, cfg)
        code, _ = self.agents("paid", attempts=3)
        self.assertEqual(len(list_evidence(self.root)), 1)

    def test_provider_failure_opens_circuit_and_next_run_skips_it(self):
        code, out = self.agents("down", "good")
        self.assertEqual(code, 0)
        self.assertIn("down", open_circuits(self.root))
        self.assertIn("exited 1 without changing any file", load_health(self.root)["down"]["last_reason"])
        (self.root / "fixed.txt").unlink()
        code, out = self.agents("down", "good", attempts=1)
        self.assertEqual(code, 0)
        self.assertIn("FAILOVER   skipping down", out)
        self.assertEqual(list_evidence(self.root)[-1]["agent"], "good")

    def test_success_closes_circuit(self):
        self.agents("down", attempts=1)
        self.assertIn("down", open_circuits(self.root))
        cfg = load_config(self.root)
        cfg["agents"]["down"] = [sys.executable, "-c", GOOD, "{prompt}"]  # provider recovered
        save_config(self.root, cfg)
        code, out = self.agents("down", attempts=1)
        self.assertIn("every agent's circuit is open; trying anyway", out)
        self.assertEqual(code, 0)
        self.assertNotIn("down", load_health(self.root))

    def test_task_failure_is_not_a_provider_failure(self):
        item = {"action": {"exit_code": 1}, "git_status_after": ["?? src/x.ts"]}
        self.assertIsNone(provider_failure_reason(item))
        self.assertIsNotNone(provider_failure_reason({"action": {"error_type": "FileNotFoundError"}}))
        self.assertIsNotNone(provider_failure_reason({"action": {"exit_code": 124, "timed_out": True}}))

    def test_templates_accept_list_and_spec_and_reject_unknown_parser(self):
        t = agent_templates({"agents": {"x": ["a", "{prompt}"]}})
        self.assertEqual(t["x"], {"argv": ["a", "{prompt}"], "cost": None})
        self.assertEqual(t["claude"]["cost"], "claude-stream")
        with self.assertRaises(ValueError):
            agent_templates({"agents": {"x": {"argv": ["a", "{prompt}"], "cost": "guess"}}})


if __name__ == "__main__":
    unittest.main()
