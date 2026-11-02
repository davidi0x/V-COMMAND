"""multi6: every task fails as shipped and passes with its reference solution; generator output is committed."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "benchmarks" / "multi6"


class MultiSuiteTests(unittest.TestCase):
    def test_generator_output_is_committed(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import gen_multi_suite
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "multi6"
            gen_multi_suite.build(out)
            for f in sorted(out.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(out)
                    self.assertEqual((SUITE / rel).read_text(encoding="utf-8"), f.read_text(encoding="utf-8"),
                                     f"{rel} is stale: run scripts/gen_multi_suite.py")

    def test_each_task_fails_unfixed_and_passes_fixed(self):
        suite = json.loads((SUITE / "suite.json").read_text(encoding="utf-8"))
        self.assertEqual(len(suite["tasks"]), 6)
        for t in suite["tasks"]:
            with tempfile.TemporaryDirectory() as temp:
                work = Path(temp) / "w"
                shutil.copytree(SUITE / t["dir"], work)
                gate = [sys.executable, *t["gates"][0][1:]]
                self.assertNotEqual(subprocess.run(gate, cwd=work, capture_output=True).returncode, 0, t["id"])
                for f in (SUITE / "_solutions" / t["id"]).iterdir():
                    shutil.copy(f, work / f.name)
                done = subprocess.run(gate, cwd=work, capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, f"{t['id']}: {(done.stderr or done.stdout)[-400:]}")


if __name__ == "__main__":
    unittest.main()
