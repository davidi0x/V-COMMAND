"""`vcmd hw`: hardware probe and a local backup model recommendation.

V/COMMAND does not run models itself. It detects what this machine can hold, which local runtimes
are present (Ollama, llama.cpp, LM Studio), recommends a model that fits, and can register a local
agent (Codex CLI in `--oss` mode against Ollama) so that `vcmd agent claude local` falls back to a
free local model when cloud providers fail. Nothing is downloaded automatically.
Standard library only.
"""
from __future__ import annotations

from pathlib import Path
import ctypes
import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any

GB = 1024 ** 3

# Ollama library tags with approximate Q4 download sizes (GB) as listed on ollama.com.
# Memory needed ≈ size + ~1.5 GB for context/KV cache. Verify with `ollama show <tag>`.
CANDIDATES = [
    {"tag": "qwen3-coder:30b", "size_gb": 19.0, "note": "MoE (≈3B active per token): good speed on unified memory / CPU"},
    {"tag": "gpt-oss:20b", "size_gb": 14.0, "note": "default model of `codex --oss`"},
    {"tag": "qwen2.5-coder:14b", "size_gb": 9.0, "note": "dense coder model"},
    {"tag": "qwen2.5-coder:7b", "size_gb": 4.7, "note": "dense coder model; fits most GPUs with 8 GB"},
    {"tag": "qwen2.5-coder:3b", "size_gb": 1.9, "note": "small; simple edits and log triage only"},
]
CONTEXT_OVERHEAD_GB = 1.5


def _run(argv: list[str], timeout: int = 5) -> str | None:
    if not shutil.which(argv[0]):
        return None
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _memory() -> tuple[float | None, float | None]:
    """(total GB, available GB) for Linux, macOS and Windows."""
    system = platform.system()
    try:
        if system == "Linux":
            info = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, _, value = line.partition(":")
                info[key] = int(value.split()[0]) * 1024
            return info["MemTotal"] / GB, info.get("MemAvailable", info.get("MemFree", 0)) / GB
        if system == "Darwin":
            total = int((_run(["sysctl", "-n", "hw.memsize"]) or "0").strip()) / GB
            vm = _run(["vm_stat"]) or ""
            page = 16384 if platform.machine() == "arm64" else 4096
            for line in vm.splitlines():
                if "page size of" in line:
                    page = int(line.split("page size of")[1].split()[0])
            pages = {}
            for line in vm.splitlines():
                key, _, value = line.partition(":")
                if value.strip().rstrip(".").isdigit():
                    pages[key.strip()] = int(value.strip().rstrip("."))
            free = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
            return (total or None), (free * page / GB if pages else None)
        if system == "Windows":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return status.ullTotalPhys / GB, status.ullAvailPhys / GB
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return None, None


def _nvidia() -> list[dict[str, Any]]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"])
    gpus = []
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[1].replace(".", "").isdigit():
            gpus.append({"name": parts[0], "vram_total_gb": float(parts[1]) / 1024,
                         "vram_free_gb": float(parts[2]) / 1024})
    return gpus


def _ollama() -> dict[str, Any]:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    url = (host if host.startswith("http") else f"http://{host}").rstrip("/") + "/api/tags"
    info: dict[str, Any] = {"binary": shutil.which("ollama"), "server": False, "models": []}
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:  # local server only
            data = json.loads(resp.read().decode("utf-8"))
        info["server"] = True
        info["models"] = sorted(m.get("name", "") for m in data.get("models", []) if isinstance(m, dict))
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return info


def probe(root: Path | None = None) -> dict[str, Any]:
    total, available = _memory()
    machine = platform.machine().lower()
    system = platform.system()
    disk = shutil.disk_usage(root or Path.cwd())
    return {
        "os": f"{system} {platform.release()}",
        "arch": machine,
        "cpu_count": os.cpu_count(),
        "apple_silicon": system == "Darwin" and machine == "arm64",
        "ram_total_gb": round(total, 1) if total else None,
        "ram_available_gb": round(available, 1) if available else None,
        "gpus": _nvidia(),
        "disk_free_gb": round(disk.free / GB, 1),
        "runtimes": {
            "ollama": _ollama(),
            "llama_cpp": shutil.which("llama-server") or shutil.which("llama-cli"),
            "lm_studio": shutil.which("lms"),
            "codex": shutil.which("codex"),
        },
    }


def memory_budget(hw: dict[str, Any]) -> dict[str, Any]:
    """How much memory a local model may use without starving the OS, IDE and compilers."""
    total = hw.get("ram_total_gb") or 0.0
    reserve = max(4.0, 0.25 * total)
    if hw.get("gpus"):
        gpu = max(hw["gpus"], key=lambda g: g["vram_free_gb"])
        return {"kind": "gpu", "device": gpu["name"], "budget_gb": round(max(0.0, gpu["vram_free_gb"] - 1.0), 1),
                "reserve_gb": 1.0, "speed": "fast"}
    if hw.get("apple_silicon"):
        return {"kind": "unified", "device": "Apple Silicon unified memory",
                "budget_gb": round(max(0.0, total - reserve), 1), "reserve_gb": round(reserve, 1), "speed": "fast"}
    available = hw.get("ram_available_gb") or 0.0
    return {"kind": "cpu", "device": "system RAM (CPU inference)",
            "budget_gb": round(max(0.0, available - reserve), 1), "reserve_gb": round(reserve, 1), "speed": "slow"}


def recommend(hw: dict[str, Any]) -> dict[str, Any]:
    budget = memory_budget(hw)
    fitting = [c for c in CANDIDATES if c["size_gb"] + CONTEXT_OVERHEAD_GB <= budget["budget_gb"]]
    if budget["kind"] == "cpu":
        # dense models are painfully slow on CPU; prefer the MoE model or small ones
        fitting = [c for c in fitting if "MoE" in c["note"] or c["size_gb"] <= 5] or fitting
    choice = fitting[0] if fitting else None
    installed = hw.get("runtimes", {}).get("ollama", {}).get("models", [])
    return {"budget": budget, "model": choice, "installed": choice is not None and choice["tag"] in installed,
            "alternatives": [c["tag"] for c in fitting[1:3]]}


def local_agent_template(model: str) -> dict[str, Any]:
    """Codex CLI against a local Ollama model (flags checked against codex-cli 0.166)."""
    return {"argv": ["codex", "exec", "--oss", "--local-provider", "ollama", "-m", model,
                     "--sandbox", "workspace-write", "{prompt}"]}


def render(hw: dict[str, Any], rec: dict[str, Any]) -> str:
    rt = hw["runtimes"]
    lines = ["V/  HARDWARE", "-" * 56,
             f"OS        {hw['os']} ({hw['arch']}), {hw['cpu_count']} logical CPUs",
             f"RAM       {hw['ram_total_gb']} GB total, {hw['ram_available_gb']} GB available",
             "GPU       " + (", ".join(f"{g['name']} ({g['vram_free_gb']:.1f}/{g['vram_total_gb']:.1f} GB free)"
                                       for g in hw["gpus"])
                             or ("Apple Silicon (unified memory)" if hw["apple_silicon"] else "none detected (NVIDIA only)")),
             f"Disk      {hw['disk_free_gb']} GB free",
             f"Ollama    {'server running' if rt['ollama']['server'] else ('installed, server not running' if rt['ollama']['binary'] else 'not found')}"
             + (f"; models: {', '.join(rt['ollama']['models'])}" if rt["ollama"]["models"] else ""),
             f"llama.cpp {rt['llama_cpp'] or 'not found'}",
             f"Codex CLI {rt['codex'] or 'not found'} (runs local models via --oss)", "",
             "V/  LOCAL BACKUP MODEL", "-" * 56]
    b = rec["budget"]
    lines.append(f"Budget    {b['budget_gb']} GB on {b['device']} (keeping {b['reserve_gb']} GB for OS/IDE; "
                 f"{'GPU/unified speed' if b['speed'] == 'fast' else 'CPU: expect slow generation'})")
    if rec["model"] is None:
        lines.append("Model     none fits safely; use cloud agents only")
    else:
        m = rec["model"]
        lines.append(f"Model     {m['tag']} (~{m['size_gb']} GB, {m['note']})")
        if rec["alternatives"]:
            lines.append(f"Also fits {', '.join(rec['alternatives'])}")
        lines.append("Status    " + ("installed in Ollama" if rec["installed"] else f"not installed: run `ollama pull {m['tag']}`"))
        lines.append(f"Register  vcmd hw --add-agent local   (then: vcmd agent claude local)")
    lines.append("Sizes are approximate Ollama Q4 downloads; nothing is downloaded by V/COMMAND.")
    return "\n".join(lines)
