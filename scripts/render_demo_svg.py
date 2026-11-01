"""Render docs/demo.svg: an animated terminal recording of the real `vcmd demo --fast` output.

Usage: python scripts/render_demo_svg.py [output.svg]
The text is captured from an actual run; nothing is hand-written.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape
import os
import subprocess
import sys
import tempfile

LINE_H = 20
CHAR_W = 8.4
PAD = 20
STEP = 0.7          # seconds between lines
HOLD = 6.0          # seconds the full screen stays before the loop restarts


def capture() -> list[str]:
    with tempfile.TemporaryDirectory() as temp:
        out = subprocess.run([sys.executable, "-m", "vcommand", "demo", "--fast"], cwd=temp,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = [line.rstrip() for line in out.stdout.splitlines()]
    # Run IDs and hashes differ per run; keep them, they are real.
    return ["$ vcmd demo"] + lines


def color(line: str) -> str:
    if line.startswith("$"):
        return "#e6edf3"
    if "FAIL" in line or "Not verified" in line:
        return "#ff7b72"
    if "PASS" in line or line.startswith("Done isn't verified. Verified"):
        return "#3fb950"
    if line.startswith("V/") or line.startswith("V/COMMAND"):
        return "#79c0ff"
    if line.startswith("["):
        return "#d2a8ff"
    if line.startswith("      "):
        return "#8b949e"
    return "#c9d1d9"


def render(lines: list[str]) -> str:
    width = int(max(len(l) for l in lines) * CHAR_W + 2 * PAD)
    height = len(lines) * LINE_H + 2 * PAD + 28
    total = len(lines) * STEP + HOLD
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="V/COMMAND demo: an agent reports done, the check fails, the next agent fixes it and the check passes">',
        "<style>",
        "text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;white-space:pre}",
    ]
    for i in range(len(lines)):
        start = i * STEP / total * 100
        end = 98.0
        parts.append(f"@keyframes l{i}{{0%,{start:.2f}%{{opacity:0}}{min(start + 0.5, end):.2f}%,{end}%{{opacity:1}}100%{{opacity:0}}}}")
        parts.append(f".l{i}{{opacity:0;animation:l{i} {total:.1f}s linear infinite}}")
    parts += [
        "</style>",
        f'<rect width="{width}" height="{height}" rx="8" fill="#0d1117"/>',
        '<circle cx="18" cy="16" r="5" fill="#ff5f56"/><circle cx="34" cy="16" r="5" fill="#ffbd2e"/>'
        '<circle cx="50" cy="16" r="5" fill="#27c93f"/>',
    ]
    for i, line in enumerate(lines):
        y = PAD + 28 + i * LINE_H
        parts.append(f'<text class="l{i}" x="{PAD}" y="{y}" fill="{color(line)}">{escape(line)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/demo.svg")
    target.write_text(render(capture()), encoding="utf-8")
    print(f"wrote {target}")
