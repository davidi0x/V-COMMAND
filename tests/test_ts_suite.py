"""Every ts200 task must fail as generated and pass with its reference fix (both ways, real Node)."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

SUITE = Path(__file__).resolve().parent.parent / "benchmarks" / "ts200"


def node_ok() -> bool:
    if not shutil.which("node"):
        return False
    out = subprocess.run(["node", "-e", "process.stdout.write(process.versions.node)"],
                         capture_output=True, text=True).stdout
    major, minor = (int(x) for x in out.split(".")[:2])
    return (major, minor) >= (22, 6)


def run_gate(task, solution: bool) -> int:
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp) / "t"
        shutil.copytree(SUITE / task["dir"], work)
        if solution:
            shutil.copytree(SUITE / task["solution"], work, dirs_exist_ok=True)
        code = 0
        for gate in task["gates"]:
            code = subprocess.run(gate, cwd=work, capture_output=True, timeout=120).returncode or code
        return code


@unittest.skipUnless(node_ok(), "node >= 22.6 required")
@unittest.skipUnless(os.environ.get("VCMD_TS_SUITE") or os.environ.get("CI") is None,
                     "set VCMD_TS_SUITE=1 to check the 200-task suite in CI")
class TsSuiteTests(unittest.TestCase):
    def test_every_task_fails_unfixed_and_passes_fixed(self):
        tasks = json.loads((SUITE / "suite.json").read_text())["tasks"]
        self.assertEqual(len(tasks), 200)
        self.assertEqual(len({t["family"] for t in tasks}), 20)
        with ThreadPoolExecutor(max_workers=8) as pool:
            unfixed = list(pool.map(lambda t: run_gate(t, False), tasks))
            fixed = list(pool.map(lambda t: run_gate(t, True), tasks))
        bad_unfixed = [t["id"] for t, c in zip(tasks, unfixed) if c == 0]
        bad_fixed = [t["id"] for t, c in zip(tasks, fixed) if c != 0]
        self.assertEqual(bad_unfixed, [], "these tasks pass without any fix")
        self.assertEqual(bad_fixed, [], "these tasks fail even with the reference fix")

    def test_solutions_are_not_in_task_templates(self):
        for task in json.loads((SUITE / "suite.json").read_text())["tasks"]:
            self.assertFalse((SUITE / task["dir"] / "_solutions").exists())
            self.assertTrue((SUITE / task["solution"]).is_dir())


if __name__ == "__main__":
    unittest.main()
