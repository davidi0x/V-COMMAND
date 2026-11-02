"""vague10: every task fails as shipped and passes with its reference solution; the suite is reproducible."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "benchmarks" / "vague10"


class VagueSuiteTests(unittest.TestCase):
    def test_generator_output_is_committed(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import gen_vague_suite
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "vague10"
            gen_vague_suite.build(out)
            for f in sorted(out.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(out)
                    self.assertEqual((SUITE / rel).read_text(), f.read_text(), f"{rel} is stale: run scripts/gen_vague_suite.py")

    def test_each_task_fails_unfixed_and_passes_fixed(self):
        suite = json.loads((SUITE / "suite.json").read_text())
        self.assertEqual(len(suite["tasks"]), 10)
        for t in suite["tasks"]:
            with tempfile.TemporaryDirectory() as temp:
                work = Path(temp) / "w"
                shutil.copytree(SUITE / t["dir"], work)
                gate = [sys.executable, *t["gates"][0][1:]]
                self.assertNotEqual(subprocess.run(gate, cwd=work, capture_output=True).returncode, 0, t["id"])
                for f in (SUITE / "_solutions" / t["id"]).iterdir():
                    shutil.copy(f, work / f.name)
                done = subprocess.run(gate, cwd=work, capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, f"{t['id']}: {done.stderr[-300:]}")


if __name__ == "__main__":
    unittest.main()
