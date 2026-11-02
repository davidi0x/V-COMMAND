from pathlib import Path
import io
import json
import shutil
import sys
import tempfile
import unittest

from vcommand.bench import load_suite, parse_arm, run_bench, wilson
from vcommand.core import init_project, load_config, save_config

SUITE_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "sample"
# Solves fix-add only when the prompt carries the code slice (i.e. the frame arm).
FRAME_SOLVER = ("import sys, pathlib; p = sys.argv[1]; "
                "pathlib.Path('calc.py').write_text('def add(a, b):\\n    return a + b\\n\\n\\ndef mul(a, b):\\n    return a * b\\n') "
                "if '## Code slice' in p and 'def add(a, b)' in p else None")


@unittest.skipUnless(shutil.which("git"), "git required")
class BenchTests(unittest.TestCase):
    def test_wilson_interval(self):
        lo, hi = wilson(8, 10)
        self.assertAlmostEqual(lo, 0.490, places=2)
        self.assertAlmostEqual(hi, 0.943, places=2)
        self.assertEqual(wilson(0, 0), (0.0, 0.0))

    def test_parse_arm_and_suite(self):
        self.assertEqual(parse_arm("claude:plain"), ("claude", "plain"))
        self.assertEqual(parse_arm("claude"), ("claude", "frame"))
        with self.assertRaises(ValueError):
            parse_arm("claude:magic")
        suite = load_suite(SUITE_DIR)
        self.assertEqual(len(suite["tasks"]), 5)

    def test_bench_measures_frame_vs_plain(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "proj"
            project.mkdir()
            init_project(project)
            cfg = load_config(project)
            cfg["agents"] = {"fake": [sys.executable, "-c", FRAME_SOLVER, "{prompt}"]}
            save_config(project, cfg)
            summary = run_bench(SUITE_DIR, ["fake:plain", "fake:frame"], project_root=project,
                                tasks_filter=["fix-add"], out_dir=Path(temp) / "out", out=io.StringIO())
            self.assertEqual(summary["arms"]["fake:plain"]["passed"], 0)
            self.assertEqual(summary["arms"]["fake:frame"]["passed"], 1)
            self.assertEqual(summary["paired"][0], {"a": "fake:plain", "b": "fake:frame", "a_only_passed": 0,
                                                    "b_only_passed": 1, "same": 0})
            self.assertIn("smoke test", summary["caveats"][0])
            rows = [json.loads(l) for l in (Path(summary["dir"]) / "results.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertTrue((Path(summary["dir"]) / "report.md").read_text().startswith("# V/COMMAND benchmark"))
            self.assertGreater(rows[1]["prompt_chars"], rows[0]["prompt_chars"])

    def test_handoff_arms_share_first_attempt(self):
        # "lazy" never fixes; "fixer" fixes only when briefed with the frame that records lazy's failure
        lazy = "import sys"
        fixer = ("import sys, pathlib; p = sys.argv[1]; "
                 "pathlib.Path('calc.py').write_text('def add(a, b):\\n    return a + b\\n\\n\\ndef mul(a, b):\\n    return a * b\\n') "
                 "if 'Hard constraints from failed attempts' in p else None")
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "proj"
            project.mkdir()
            init_project(project)
            cfg = load_config(project)
            cfg["agents"] = {"lazy": [sys.executable, "-c", lazy, "{prompt}"],
                             "fixer": [sys.executable, "-c", fixer, "{prompt}"]}
            save_config(project, cfg)
            summary = run_bench(SUITE_DIR, [], handoffs=["lazy>fixer"], project_root=project, jobs=2,
                                tasks_filter=["fix-add", "paginate"], out_dir=Path(temp) / "out", out=io.StringIO())
            plain, frame = summary["arms"]["lazy>fixer:plain"], summary["arms"]["lazy>fixer:frame"]
            self.assertEqual((plain["first_attempt_passed"], frame["first_attempt_passed"]), (0, 0))
            self.assertEqual((plain["rescued"], frame["rescued"]), (0, 1))  # only fix-add is solvable by fixer
            self.assertIn("Handoff after a failed first attempt", (Path(summary["dir"]) / "report.md").read_text())

    def test_provider_failures_are_excluded_and_resumable(self):
        import vcommand.bench as bench_mod
        down = "import sys; sys.exit(1)"   # provider refused: exit 1, no file changes
        fixer = ("import pathlib; pathlib.Path('calc.py').write_text("
                 "'def add(a, b):\\n    return a + b\\n\\n\\ndef mul(a, b):\\n    return a * b\\n')")
        saved = bench_mod.INFRA_BACKOFF_S
        bench_mod.INFRA_BACKOFF_S = (0,)
        self.addCleanup(setattr, bench_mod, "INFRA_BACKOFF_S", saved)
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "proj"
            project.mkdir()
            init_project(project)
            cfg = load_config(project)
            cfg["agents"] = {"agent": [sys.executable, "-c", down, "{prompt}"]}
            save_config(project, cfg)
            summary = run_bench(SUITE_DIR, ["agent:plain"], project_root=project, tasks_filter=["fix-add", "paginate"],
                                out_dir=Path(temp) / "out", out=io.StringIO())
            arm = summary["arms"]["agent:plain"]
            self.assertEqual((arm["runs"], arm["infra_errors"]), (0, 2))   # not counted as task failures
            cfg["agents"] = {"agent": [sys.executable, "-c", fixer, "{prompt}"]}   # provider recovered
            save_config(project, cfg)
            resumed = run_bench(SUITE_DIR, ["agent:plain"], project_root=project, tasks_filter=["fix-add", "paginate"],
                                resume=Path(summary["dir"]), out=io.StringIO())
            arm = resumed["arms"]["agent:plain"]
            self.assertEqual((arm["runs"], arm["passed"], arm["infra_errors"]), (2, 1, 0))
            rows = (Path(summary["dir"]) / "results.jsonl").read_text().splitlines()
            self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
