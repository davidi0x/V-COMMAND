from pathlib import Path
import contextlib
import io
import json
import tempfile
import unittest

from vcommand.hw import probe, recommend, memory_budget, local_agent_template
from vcommand.core import init_project, load_config
from vcommand.cli import main


def machine(ram=16.0, avail=12.0, gpus=None, apple=False, models=None):
    return {"ram_total_gb": ram, "ram_available_gb": avail, "gpus": gpus or [], "apple_silicon": apple,
            "runtimes": {"ollama": {"models": models or []}}}


class HardwareTests(unittest.TestCase):
    def test_probe_runs_on_this_machine(self):
        hw = probe()
        self.assertIn("cpu_count", hw)
        self.assertIsInstance(hw["gpus"], list)
        self.assertIsInstance(recommend(hw)["budget"]["budget_gb"], float)

    def test_gpu_budget_uses_free_vram(self):
        # budget = free VRAM - 1 GB; a model needs its size + 1.5 GB context
        rec = recommend(machine(gpus=[{"name": "RTX", "vram_total_gb": 24.0, "vram_free_gb": 20.0}]))
        self.assertEqual(rec["budget"]["kind"], "gpu")
        self.assertEqual(rec["budget"]["budget_gb"], 19.0)
        self.assertEqual(rec["model"]["tag"], "gpt-oss:20b")  # qwen3-coder:30b needs 20.5 GB
        rec2 = recommend(machine(gpus=[{"name": "RTX", "vram_total_gb": 24.0, "vram_free_gb": 23.0}]))
        self.assertEqual(rec2["model"]["tag"], "qwen3-coder:30b")

    def test_apple_unified_keeps_reserve(self):
        b = memory_budget(machine(ram=32.0, apple=True))
        self.assertEqual((b["kind"], b["reserve_gb"], b["budget_gb"]), ("unified", 8.0, 24.0))

    def test_cpu_prefers_small_or_moe_and_reports_installed(self):
        rec = recommend(machine(ram=16.0, avail=15.0, models=["qwen2.5-coder:7b"]))
        self.assertEqual(rec["budget"]["speed"], "slow")
        self.assertEqual(rec["model"]["tag"], "qwen2.5-coder:7b")
        self.assertTrue(rec["installed"])

    def test_nothing_fits_tiny_machine(self):
        self.assertIsNone(recommend(machine(ram=4.0, avail=3.0))["model"])

    def test_add_agent_writes_codex_oss_template(self):
        self.assertIn("--oss", local_agent_template("m")["argv"])
        with tempfile.TemporaryDirectory() as temp:
            import os
            cwd = os.getcwd()
            os.chdir(temp)
            try:
                init_project(Path(temp))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["hw", "--add-agent", "local", "--model", "qwen2.5-coder:7b"]), 0)
                agent = load_config(Path(temp))["agents"]["local"]
                self.assertEqual(agent["argv"][agent["argv"].index("-m") + 1], "qwen2.5-coder:7b")
                with contextlib.redirect_stdout(io.StringIO()) as buf:
                    self.assertEqual(main(["hw", "--json"]), 0)
                self.assertIn("recommendation", json.loads(buf.getvalue()))
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
