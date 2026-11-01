from pathlib import Path
import tempfile
import unittest

from vcommand.core import init_project
from vcommand.slice import extract_symbols, build_slice, parse_focus, render_slice
from vcommand.state import start_task, set_focus, build_frame, render_frame, add_ledger_entry, preflight_hints

AUTH_TS = '''import { RedisSessionStore } from "../session/RedisSessionStore";

export interface SessionToken { value: string; expires: number }
export type UserId = string;

/* a comment with braces { { { */
export class AuthService {
  private store: RedisSessionStore;

  constructor(store: RedisSessionStore) {
    this.store = store;
  }

  async login(email: string, pass: string): Promise<SessionToken> {
    const msg = "not a brace } here";
    const t = `template ${email} with } brace`;
    const helper = (x: number) => {
      return x + 1;
    };
    // closing brace in comment }
    return { value: email + pass, expires: helper(1) };
  }

  async confirmPasswordReset(userId: UserId): Promise<boolean> {
    const removed = await this.store.invalidateAllForUser(userId);
    return removed >= 0;
  }
}

export const hashPassword = async (raw: string): Promise<string> => {
  return raw.split("").reverse().join("");
};

export function isStrong(p: string) {
  return p.length > 8;
}
'''

CALLER_TS = '''import { AuthService } from "./AuthService";
export function route(a: AuthService) {
  return a.login("x", "y");
}
'''

TEST_TS = '''import { AuthService } from "../AuthService";
test("login", async () => { await new AuthService(null as any).login("a", "b"); });
'''

PY = '''import os

def top(a, b):
    return a + b

class Store:
    @staticmethod
    def make():
        return Store()

    def invalidate(self, user):
        def inner():
            return 1
        return inner()
'''


class SymbolTests(unittest.TestCase):
    def test_typescript_symbols_and_ranges(self):
        syms = {s["name"]: s for s in extract_symbols(Path("AuthService.ts"), AUTH_TS)}
        for name in ("SessionToken", "UserId", "AuthService", "AuthService.constructor", "AuthService.login",
                     "AuthService.confirmPasswordReset", "hashPassword", "isStrong"):
            self.assertIn(name, syms)
        lines = AUTH_TS.splitlines()
        login = syms["AuthService.login"]
        self.assertTrue(lines[login["start"] - 1].strip().startswith("async login"))
        self.assertEqual(lines[login["end"] - 1].strip(), "}")  # braces in strings/comments/template skipped
        self.assertEqual(lines[login["end"]].strip(), "")
        self.assertNotIn("AuthService.helper", syms)  # nested arrow is not a class member
        self.assertEqual(syms["UserId"]["start"], syms["UserId"]["end"])
        cls = syms["AuthService"]
        self.assertEqual(lines[cls["end"] - 1], "}")

    def test_python_symbols(self):
        syms = {s["name"]: s for s in extract_symbols(Path("store.py"), PY)}
        self.assertEqual(set(syms), {"top", "Store", "Store.make", "Store.invalidate"})
        self.assertEqual(syms["Store.make"]["start"], 7)  # includes decorator
        self.assertEqual(syms["Store.invalidate"]["kind"], "method")

    def test_parse_focus(self):
        self.assertEqual(parse_focus("src/a.ts:AuthService.login"), ("src/a.ts", "AuthService.login"))
        self.assertEqual(parse_focus("src/a.ts"), ("src/a.ts", None))
        self.assertEqual(parse_focus("src\\a.ts:x"), ("src/a.ts", "x"))
        self.assertEqual(parse_focus("src/a.ts:42"), ("src/a.ts:42", None))


class SliceFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src" / "auth" / "__tests__").mkdir(parents=True)
        (self.root / "src" / "auth" / "AuthService.ts").write_text(AUTH_TS)
        (self.root / "src" / "auth" / "routes.ts").write_text(CALLER_TS)
        (self.root / "src" / "auth" / "__tests__" / "auth.spec.ts").write_text(TEST_TS)
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "x.ts").write_text("login()")
        init_project(self.root)
        start_task(self.root, "Fix login")

    def test_slice_symbol_code_and_blast_radius(self):
        sl = build_slice(self.root, ["src/auth/AuthService.ts:AuthService.login"])
        self.assertEqual(sl["problems"], [])
        sym = sl["symbols"][0]
        self.assertIn("async login(email", sym["code"])
        self.assertNotIn("confirmPasswordReset", sym["code"])
        refs = {(r["file"], r["kind"]) for r in sl["references"]}
        self.assertIn(("src/auth/__tests__/auth.spec.ts", "test"), refs)
        self.assertIn(("src/auth/routes.ts", "use"), refs)
        self.assertFalse(any(r["file"].startswith("node_modules") for r in sl["references"]))
        self.assertEqual(sl["references"][0]["kind"], "test")  # tests ranked first

    def test_whole_file_focus_gives_outline(self):
        sl = build_slice(self.root, ["src/auth/AuthService.ts"])
        names = [o["name"] for o in sl["symbols"][0]["outline"]]
        self.assertIn("AuthService.confirmPasswordReset", names)
        self.assertTrue(any(r["kind"] == "import" for r in sl["references"]))

    def test_missing_symbol_reported_not_raised(self):
        sl = build_slice(self.root, ["src/auth/AuthService.ts:nope", "missing.ts"])
        self.assertEqual(len(sl["problems"]), 2)

    def test_frame_carries_slice_and_token_tracks_code(self):
        set_focus(self.root, ["src/auth/AuthService.ts:AuthService.login"])
        frame = build_frame(self.root)
        text = render_frame(frame)
        self.assertIn("## Code slice", text)
        self.assertIn("async login(email", text)
        self.assertIn("## Blast radius", text)
        path = self.root / "src" / "auth" / "AuthService.ts"
        path.write_text(AUTH_TS.replace("pass: string)", "password: string)"))
        self.assertNotEqual(build_frame(self.root)["continuity_token"], frame["continuity_token"])
        self.assertEqual(render_slice({"symbols": [], "references": [], "problems": []}), [])


class PreflightTests(unittest.TestCase):
    def test_hints_are_counts_and_need_repetition(self):
        one = [{"failed_checks": ["npm test"], "files": ["a.ts"]}]
        self.assertEqual(preflight_hints(one), [])
        ledger = one + [{"failed_checks": ["npm test"], "files": ["a.ts", "b.ts"]},
                        {"failed_checks": ["tsc"], "files": ["b.ts"]}]
        hints = preflight_hints(ledger, focus=["b.ts:X"])
        self.assertTrue(hints[0].startswith("Gate `npm test` failed in 2 of 3"))
        self.assertIn("`b.ts` was changed in 2 of 3", hints[1])  # focused file ranked before a.ts
        self.assertIn("`a.ts` was changed in 2 of 3", hints[2])
        self.assertFalse(any("tsc" in h for h in hints))

    def test_frame_shows_hints_from_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            init_project(root)
            start_task(root, "goal")
            for _ in range(2):
                add_ledger_entry(root, tried="x", failure="y", files=["src/a.ts"], failed_checks=["npm test"])
            text = render_frame(build_frame(root))
            self.assertIn("## Pre-flight warnings", text)
            self.assertIn("Gate `npm test` failed in 2 of 2", text)


if __name__ == "__main__":
    unittest.main()


try:
    import tree_sitter  # noqa: F401
    import tree_sitter_typescript  # noqa: F401
    HAVE_TS = True
except ImportError:
    HAVE_TS = False


@unittest.skipUnless(HAVE_TS, "tree-sitter not installed (pip install 'vcommand-cli[ast]')")
class TreeSitterTests(unittest.TestCase):
    def test_tree_sitter_matches_scanner_on_key_symbols(self):
        import os
        from vcommand.slice import slice_parser_name
        self.assertEqual(slice_parser_name(), "tree-sitter")
        ts = {s["name"]: s for s in extract_symbols(Path("AuthService.ts"), AUTH_TS)}
        os.environ["VCOMMAND_SLICE_PARSER"] = "scanner"
        try:
            sc = {s["name"]: s for s in extract_symbols(Path("AuthService.ts"), AUTH_TS)}
        finally:
            del os.environ["VCOMMAND_SLICE_PARSER"]
        for name in ("SessionToken", "UserId", "AuthService", "AuthService.login",
                     "AuthService.confirmPasswordReset", "hashPassword", "isStrong"):
            self.assertIn(name, ts)
            self.assertEqual((ts[name]["start"], ts[name]["end"]), (sc[name]["start"], sc[name]["end"]), name)
        self.assertNotIn("AuthService.helper", ts)

    def test_tree_sitter_handles_syntax_the_scanner_gets_wrong(self):
        # a regex literal containing a brace confuses brace matching; tree-sitter parses it correctly
        code = "export function f(s: string) {\n  return s.replace(/}/g, '');\n}\nexport function g() {\n  return 1;\n}\n"
        syms = {s["name"]: s for s in extract_symbols(Path("x.ts"), code)}
        self.assertEqual((syms["f"]["start"], syms["f"]["end"]), (1, 3))
        self.assertEqual((syms["g"]["start"], syms["g"]["end"]), (4, 6))
