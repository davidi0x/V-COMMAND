"""Workspace files and changes: the file tree, a safe editor backend, and git status / diff / revert.

Every path is resolved and must stay inside the project (no `..`, no symlink escapes) and never inside
`.git`. Writes are atomic and refuse to overwrite a file that changed on disk after it was opened.
Standard library only; git is used when the project is a repository.
"""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import tempfile
from typing import Any

from .core import CONFIG_DIR

MAX_READ = 1_000_000
MAX_WRITE = 2_000_000
MAX_DIFF = 400_000
MAX_TREE = 6000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build", ".next"}
TOOL_DIRS = (CONFIG_DIR + "/", ".claude/", ".codex/")


class WorkspaceError(ValueError):
    pass


def _git(root: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=timeout, check=False)


def is_repo(root: Path) -> bool:
    try:
        return _git(root, "rev-parse", "--is-inside-work-tree", timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def safe_path(root: Path, rel: str, *, must_exist: bool = True) -> Path:
    if not isinstance(rel, str) or not rel or "\0" in rel:
        raise WorkspaceError("Missing path")
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        inside = target.relative_to(base)
    except ValueError as error:
        raise WorkspaceError("Path is outside the project") from error
    if ".git" in inside.parts:
        raise WorkspaceError("The .git directory is not editable here")
    if must_exist and not target.is_file():
        raise WorkspaceError(f"No such file: {rel}")
    return target


def branch(root: Path) -> str | None:
    try:
        out = _git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    name = out.stdout.decode("utf-8", "replace").strip()
    return name if out.returncode == 0 and name else None


def tree(root: Path) -> dict[str, Any]:
    paths: list[str] = []
    if is_repo(root):
        out = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        paths = [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]
    else:
        base = root.resolve()
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                paths.append(str(Path(dirpath, f).relative_to(base)).replace(os.sep, "/"))
                if len(paths) > MAX_TREE:
                    break
    paths = sorted({p for p in paths if (root / p).is_file() and not p.startswith(TOOL_DIRS)})
    truncated = len(paths) > MAX_TREE
    return {"files": paths[:MAX_TREE], "truncated": truncated}


def read_file(root: Path, rel: str) -> dict[str, Any]:
    p = safe_path(root, rel)
    size = p.stat().st_size
    if size > MAX_READ:
        raise WorkspaceError(f"File is {size // 1024} KB; the editor opens files up to {MAX_READ // 1024} KB")
    raw = p.read_bytes()
    if b"\0" in raw[:8000]:
        raise WorkspaceError("Binary file")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceError("Not UTF-8 text") from error
    st = p.stat()
    # nanosecond timestamps exceed JavaScript's 2**53 integer range: they travel as text
    return {"path": rel, "content": text, "size": size, "mtime_ns": str(st.st_mtime_ns),
            "crlf": "\r\n" in text, "executable": bool(st.st_mode & 0o111)}


def write_file(root: Path, rel: str, content: str, *, base_mtime_ns: int | str | None = None, create: bool = False) -> dict[str, Any]:
    if not isinstance(content, str):
        raise WorkspaceError("content must be text")
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE:
        raise WorkspaceError("File too large for the editor")
    p = safe_path(root, rel, must_exist=not create)
    if p.exists():
        if base_mtime_ns is not None and p.stat().st_mtime_ns != int(base_mtime_ns):
            raise WorkspaceError("changed on disk since you opened it (an agent or another tool wrote it); "
                                 "reload before saving")
        mode = p.stat().st_mode & 0o777
    else:
        if not create:
            raise WorkspaceError(f"No such file: {rel}")
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".vcmd-save-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, p)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"path": rel, "mtime_ns": str(p.stat().st_mtime_ns), "size": len(data)}


def status(root: Path) -> list[dict[str, str]]:
    if not is_repo(root):
        return []
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    items, entries = [], out.stdout.decode("utf-8", "replace").split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        x, y, path = e[0], e[1], e[3:]
        if x in "RC" and i < len(entries):  # rename/copy: the next entry is the origin path
            i += 1
        if path.startswith(TOOL_DIRS):
            continue
        label = "untracked" if (x, y) == ("?", "?") else "deleted" if "D" in (x, y) else \
                "added" if "A" in (x, y) else "renamed" if "R" in (x, y) else "modified"
        items.append({"path": path, "x": x, "y": y, "label": label})
    return sorted(items, key=lambda d: d["path"])


def diff(root: Path, rel: str) -> dict[str, Any]:
    """Unified diff of one file against HEAD (untracked files are shown as all-added)."""
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        inside = target.relative_to(base)
    except ValueError as error:
        raise WorkspaceError("Path is outside the project") from error
    if ".git" in inside.parts:
        raise WorkspaceError("The .git directory is not viewable here")
    st = {s["path"]: s for s in status(root)}.get(rel)
    if st is None:
        return {"path": rel, "label": "unchanged", "diff": ""}
    if st["label"] == "untracked":
        if not target.is_file():
            return {"path": rel, "label": "untracked", "diff": ""}
        text = target.read_bytes()[:MAX_DIFF].decode("utf-8", "replace")
        lines = text.splitlines()
        body = f"--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n" + "\n".join("+" + l for l in lines) + "\n"
        return {"path": rel, "label": "untracked", "diff": f"diff --git a/{rel} b/{rel}\nnew file\n" + body}
    out = _git(root, "diff", "HEAD", "--no-color", "--", rel)
    text = out.stdout[:MAX_DIFF].decode("utf-8", "replace")
    return {"path": rel, "label": st["label"], "diff": text, "truncated": len(out.stdout) > MAX_DIFF}


def revert(root: Path, rel: str) -> dict[str, Any]:
    """Discard the changes to one file: restore it from HEAD, or delete it if it is untracked."""
    base = root.resolve()
    target = (base / rel).resolve()
    try:
        inside = target.relative_to(base)
    except ValueError as error:
        raise WorkspaceError("Path is outside the project") from error
    if ".git" in inside.parts:
        raise WorkspaceError("Refusing to touch .git")
    st = {s["path"]: s for s in status(root)}.get(rel)
    if st is None:
        raise WorkspaceError("Nothing to revert")
    if st["label"] == "untracked":
        if target.is_file():
            target.unlink()
    else:
        out = _git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", rel)
        if out.returncode != 0:
            raise WorkspaceError(out.stderr.decode("utf-8", "replace").strip()[:300] or "git restore failed")
    return {"path": rel, "reverted": True}
