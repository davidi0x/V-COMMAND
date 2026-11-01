"""Code slice for the context frame: the focused symbols' source plus their blast radius.

Instead of letting an agent search the repository, the frame carries exactly the code the task is
about: the definition of each focused symbol, an outline of its file, and every place that
references it (callers, importers, tests).

Parsing is standard-library only:
* Python: the `ast` module (exact line ranges).
* TypeScript / JavaScript: a declaration scanner with brace matching that skips strings, template
  literals and comments. It is a heuristic, not a full parser; unusual syntax may be missed.
"""
from __future__ import annotations

from pathlib import Path
import ast
import re
import shutil
import subprocess
from typing import Any

PY_EXT = {".py"}
JS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
SOURCE_EXT = PY_EXT | JS_EXT
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".vcommand", ".next",
             "coverage", "target", ".mypy_cache", ".pytest_cache"}

MAX_SYMBOL_LINES = 120
MAX_SLICE_CHARS = 12_000
MAX_REFERENCES = 25
MAX_FILE_BYTES = 1_000_000


# ---------------------------------------------------------------- symbol extraction

def _python_symbols(text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    out: list[dict[str, Any]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                start = min([d.lineno for d in child.decorator_list] + [child.lineno])
                kind = "class" if isinstance(child, ast.ClassDef) else ("method" if prefix else "function")
                out.append({"name": name, "kind": kind, "start": start, "end": child.end_lineno or child.lineno,
                            "signature": lines[child.lineno - 1].strip()})
                if isinstance(child, ast.ClassDef):
                    visit(child, name + ".")

    visit(tree, "")
    return out


_JS_DECL = [
    ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)")),
    ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("interface", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?interface\s+([A-Za-z_$][\w$]*)")),
    ("enum", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+([A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?type\s+([A-Za-z_$][\w$]*)\s*(?:<[^=]*>)?\s*=")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
                            r"(?:async\s+)?(?:function\b|(?:<[^>]*>)?\([^)]*\)\s*(?::[^=]+)?=>|[A-Za-z_$][\w$]*\s*=>)")),
]
_JS_METHOD = re.compile(r"^\s+(?:(?:public|private|protected|static|readonly|async|override|get|set)\s+)*"
                        r"\*?\s*(#?[A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(")
_NOT_METHODS = {"if", "for", "while", "switch", "catch", "return", "function", "with", "else", "do", "new",
                "typeof", "await", "super"}


def _block_end(lines: list[str], start: int) -> int:
    """Index of the line where the declaration starting at `start` ends (brace matching that skips
    strings, template literals and comments). Falls back to the first `;` line for brace-less forms."""
    depth = 0
    opened = False
    in_block_comment = False
    for i in range(start, len(lines)):
        line = lines[i]
        j = 0
        quote = ""
        while j < len(line):
            ch = line[j]
            nxt = line[j + 1] if j + 1 < len(line) else ""
            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    j += 1
            elif quote:
                if ch == "\\":
                    j += 1
                elif ch == quote:
                    quote = ""
            elif ch == "/" and nxt == "/":
                break
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                j += 1
            elif ch in "'\"`":
                quote = ch
            elif ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
                if opened and depth <= 0:
                    return i
            elif ch == ";" and not opened and depth == 0:
                return i
            j += 1
        # template literals may span lines; strings may not — reset non-template quotes
        if quote and quote != "`":
            quote = ""
    return len(lines) - 1


def _js_symbols(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    out: list[dict[str, Any]] = []
    classes: list[tuple[str, int, int]] = []
    for i, line in enumerate(lines):
        for kind, pattern in _JS_DECL:
            m = pattern.match(line)
            if m:
                end = _block_end(lines, i)
                out.append({"name": m.group(1), "kind": kind, "start": i + 1, "end": end + 1,
                            "signature": line.strip()})
                if kind == "class":
                    classes.append((m.group(1), i, end))
                break
    for cls, start, end in classes:
        body = [lines[i] for i in range(start + 1, end) if lines[i].strip()]
        if not body:
            continue
        member_indent = min(len(l) - len(l.lstrip()) for l in body)
        for i in range(start + 1, end):
            if len(lines[i]) - len(lines[i].lstrip()) != member_indent:
                continue  # only direct members, not code nested inside method bodies
            m = _JS_METHOD.match(lines[i])
            if not m or m.group(1) in _NOT_METHODS:
                continue
            if not re.search(r"\)\s*(?::[^{;]+)?\{", lines[i]) and not lines[i].rstrip().endswith(("(", ",")):
                continue  # a call or an abstract/overload signature, not a method body
            mend = _block_end(lines, i)
            out.append({"name": f"{cls}.{m.group(1)}", "kind": "method", "start": i + 1, "end": mend + 1,
                        "signature": lines[i].strip()})
    return sorted(out, key=lambda s: s["start"])


def extract_symbols(path: Path, text: str | None = None) -> list[dict[str, Any]]:
    if text is None:
        text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix in PY_EXT:
        return _python_symbols(text)
    if path.suffix in JS_EXT:
        return _js_symbols(text)
    return []


# ---------------------------------------------------------------- repository scan

def source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if shutil.which("git"):
        try:
            proc = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, timeout=30, check=False)
            if proc.returncode == 0:
                files = [root / p for p in proc.stdout.splitlines()]
        except (OSError, subprocess.TimeoutExpired):
            files = []
    if not files:
        files = [p for p in root.rglob("*") if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS)]
    return sorted(p for p in files if p.suffix in SOURCE_EXT and p.is_file()
                  and not (set(p.relative_to(root).parts) & SKIP_DIRS))


def _is_test(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return ("test" in rel.split("/")[:-1] or "tests" in rel.split("/")[:-1] or "__tests__" in rel
            or name.startswith("test_") or ".test." in name or ".spec." in name or name.endswith("_test.py"))


# ---------------------------------------------------------------- slice

def parse_focus(spec: str) -> tuple[str, str | None]:
    """'src/a.ts:AuthService.login' -> ('src/a.ts', 'AuthService.login'); 'src/a.ts' -> (..., None).
    A trailing ':<digits>' is not treated as a symbol (Windows drive letters are kept)."""
    spec = spec.strip().replace("\\", "/")
    head, sep, tail = spec.rpartition(":")
    if sep and head and tail and not tail.isdigit() and len(head) > 1:
        return head, tail
    return spec, None


def build_slice(root: Path, focus: list[str]) -> dict[str, Any]:
    files = None  # lazily scanned once
    symbols_out: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    problems: list[str] = []
    budget = MAX_SLICE_CHARS
    for spec in focus:
        rel, symbol = parse_focus(spec)
        path = (root / rel)
        if not path.is_file():
            problems.append(f"{rel}: file not found")
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            problems.append(f"{rel}: larger than {MAX_FILE_BYTES} bytes, skipped")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        syms = extract_symbols(path, text)
        if symbol is None:
            symbols_out.append({"file": rel, "symbol": None, "outline": [
                {"name": s["name"], "kind": s["kind"], "line": s["start"], "signature": s["signature"][:160]}
                for s in syms]})
            names = [s["name"].split(".")[-1] for s in syms if s["kind"] != "method"]
        else:
            match = [s for s in syms if s["name"] == symbol] or [s for s in syms if s["name"].split(".")[-1] == symbol]
            if not match:
                problems.append(f"{rel}: symbol {symbol} not found")
                continue
            s = max(match, key=lambda m: m["end"] - m["start"])  # overloads: take the implementation
            end = min(s["end"], s["start"] + MAX_SYMBOL_LINES - 1)
            code = "\n".join(lines[s["start"] - 1:end])
            truncated = end < s["end"]
            if len(code) > budget:
                code = code[:max(budget, 0)]
                truncated = True
            budget -= len(code)
            symbols_out.append({"file": rel, "symbol": s["name"], "kind": s["kind"], "lines": [s["start"], s["end"]],
                                "signature": s["signature"][:200], "code": code, "truncated": truncated})
            names = [s["name"].split(".")[-1]]
        if files is None:
            files = source_files(root)
        references.extend(_references(root, files, rel, names))
    seen = set()
    unique = []
    for r in references:
        key = (r["file"], r["line"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return {"symbols": symbols_out, "references": unique[:MAX_REFERENCES],
            "references_omitted": max(0, len(unique) - MAX_REFERENCES), "problems": problems,
            "parser": "python-ast + js/ts declaration scanner (heuristic)"}


def _references(root: Path, files: list[Path], target_rel: str, names: list[str]) -> list[dict[str, Any]]:
    if not names:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True)) + r")\b")
    stem = Path(target_rel).with_suffix("").as_posix()
    module_tail = stem.rsplit("/", 1)[-1]
    out = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if rel == target_rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace") if path.stat().st_size <= MAX_FILE_BYTES else ""
        except OSError:
            continue
        for no, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                imports = ("import" in line or "require(" in line) and module_tail in line
                out.append({"file": rel, "line": no, "text": line.strip()[:160],
                            "kind": "import" if imports else ("test" if _is_test(rel) else "use")})
    # tests and imports first: they are what a change most often breaks
    order = {"test": 0, "import": 1, "use": 2}
    return sorted(out, key=lambda r: (order[r["kind"]], r["file"], r["line"]))


def render_slice(code_slice: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if not code_slice["symbols"] and not code_slice["problems"]:
        return out
    out.append("## Code slice (focused symbols; read other files only if needed)")
    for s in code_slice["symbols"]:
        if s.get("symbol") is None:
            out.append(f"### {s['file']} — outline")
            out += [f"- L{o['line']} {o['kind']} `{o['signature']}`" for o in s["outline"]] or ["- (no symbols found)"]
        else:
            lang = "python" if s["file"].endswith(".py") else "ts"
            out.append(f"### {s['file']}:{s['lines'][0]}-{s['lines'][1]} `{s['symbol']}` ({s['kind']})"
                       + (" — truncated" if s["truncated"] else ""))
            out += [f"```{lang}", s["code"], "```"]
    for p in code_slice["problems"]:
        out.append(f"- note: {p}")
    if code_slice["references"]:
        out.append("")
        out.append("## Blast radius (references to the focused code)")
        out += [f"- [{r['kind']}] {r['file']}:{r['line']} `{r['text']}`" for r in code_slice["references"]]
        if code_slice["references_omitted"]:
            out.append(f"- …{code_slice['references_omitted']} more")
    out.append("")
    return out
