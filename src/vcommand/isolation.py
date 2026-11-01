"""Per-attempt isolation in disposable git worktrees.

An attempt runs in a fresh worktree checked out at HEAD, outside the repository. The gates run
there too. Only a verified attempt's changes are applied to the developer's working tree (as a
patch); failed attempts are discarded, so the next agent starts clean and learns from the ledger
instead of inheriting broken edits. Standard library only.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from .core import CONFIG_DIR

DEFAULT_LINKS = ("node_modules",)          # heavy, untracked dependency dirs shared via symlink
TOOL_STATE = (CONFIG_DIR + "/", ".claude/", ".codex/")


class IsolationError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path, *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=cwd, input=input_bytes, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise IsolationError(f"git {args[0]} failed: {type(error).__name__}") from error


def _err(proc: subprocess.CompletedProcess) -> str:
    lines = proc.stderr.decode("utf-8", "replace").strip().splitlines()
    return lines[-1] if lines else f"exit {proc.returncode}"


def work_changes(cwd: Path, extra_excludes: tuple[str, ...] = ()) -> list[str]:
    """Changed paths (tracked and untracked, deletions included) minus tool state and `extra_excludes`.

    Uses `git status -z` and filters in Python: pathspec excludes make `git add` fail when an
    excluded directory exists and is gitignored (the common case for .vcommand/)."""
    proc = _git(["status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"], cwd)
    if proc.returncode != 0:
        raise IsolationError(f"git status failed: {_err(proc)}")
    skip = TOOL_STATE + tuple(e.rstrip("/") + "/" for e in extra_excludes)
    paths = []
    for entry in proc.stdout.decode("utf-8", "replace").split("\0"):
        if len(entry) > 3:
            path = entry[3:]
            if not (path + "/").startswith(skip) and path not in extra_excludes:
                paths.append(path)
    return paths


def stage(cwd: Path, paths: list[str]) -> None:
    for start in range(0, len(paths), 200):  # keep command lines short on Windows
        proc = _git(["add", "-A", "--", *paths[start:start + 200]], cwd)
        if proc.returncode != 0:
            raise IsolationError(f"git add failed: {_err(proc)}")


def ensure_clean_repo(root: Path) -> str:
    """Return HEAD. Refuse when the working tree has changes, since a worktree would not contain them."""
    if not shutil.which("git"):
        raise IsolationError("--isolate needs git on PATH")
    head = _git(["rev-parse", "--verify", "HEAD"], root)
    if head.returncode != 0:
        raise IsolationError("--isolate needs a git repository with at least one commit")
    status = _git(["status", "--porcelain=v1", "--untracked-files=normal"], root)
    dirty = [line for line in status.stdout.decode("utf-8", "replace").splitlines()
             if len(line) > 3 and not line[3:].startswith(TOOL_STATE)]
    if dirty:
        raise IsolationError("--isolate starts every attempt from HEAD; commit or stash these changes first: "
                             + ", ".join(line[3:] for line in dirty[:5]) + (" …" if len(dirty) > 5 else ""))
    return head.stdout.decode().strip()


class Worktree:
    """A disposable detached worktree at `head`, outside the repository."""

    def __init__(self, root: Path, head: str, links: tuple[str, ...] | list[str] = DEFAULT_LINKS):
        self.root = root
        self.head = head
        self.links = [name for name in links if (root / name).is_dir()]
        self._parent = Path(tempfile.mkdtemp(prefix="vcmd-attempt-"))
        self.path = self._parent / "wt"
        self.warnings: list[str] = []
        self.extra_excludes: tuple[str, ...] = ("VCOMMAND_QUESTION.md",)  # queue signal, never product code

    def __enter__(self) -> "Worktree":
        proc = _git(["worktree", "add", "--detach", str(self.path), self.head], self.root)
        if proc.returncode != 0:
            shutil.rmtree(self._parent, ignore_errors=True)
            raise IsolationError(f"git worktree add failed: {_err(proc)}")
        for name in self.links:
            try:
                os.symlink(self.root / name, self.path / name, target_is_directory=True)
            except OSError as error:  # e.g. Windows without symlink privilege
                self.warnings.append(f"could not link {name} ({type(error).__name__}); install dependencies in the worktree")
        return self

    def __exit__(self, *exc) -> None:
        self.remove()

    def remove(self) -> None:
        _git(["worktree", "remove", "--force", str(self.path)], self.root)
        shutil.rmtree(self._parent, ignore_errors=True)
        _git(["worktree", "prune"], self.root)

    def patch(self) -> bytes:
        """Binary diff of everything the attempt changed, excluding tool state and linked dirs."""
        stage(self.path, work_changes(self.path, tuple(self.links) + self.extra_excludes))
        diff = _git(["diff", "--cached", "--binary", self.head], self.path)
        if diff.returncode != 0:
            raise IsolationError(f"git diff in worktree failed: {_err(diff)}")
        return diff.stdout

    def apply_to_root(self) -> list[str]:
        """Apply the attempt's changes to the main working tree. Returns changed paths."""
        patch = self.patch()
        if not patch.strip():
            return []
        check = _git(["apply", "--check", "--whitespace=nowarn", "-"], self.root, input_bytes=patch)
        if check.returncode != 0:
            raise IsolationError(f"verified changes do not apply cleanly to the working tree: {_err(check)}")
        applied = _git(["apply", "--whitespace=nowarn", "-"], self.root, input_bytes=patch)
        if applied.returncode != 0:
            raise IsolationError(f"git apply failed: {_err(applied)}")
        names = _git(["diff", "--cached", "--name-only", self.head], self.path)
        return names.stdout.decode("utf-8", "replace").split()
