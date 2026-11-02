"""API keys stored as secrets, outside every repository.

Backends, best available first:
* macOS Keychain            (`security` CLI)
* Windows DPAPI             (CryptProtectData via ctypes; encrypted for the current Windows user)
* Linux Secret Service      (`secret-tool`, GNOME Keyring / KWallet)
* file fallback             (~/.config/vcommand/secrets.json, permissions 0600, NOT encrypted)

Only names are ever listed; values are never printed or sent to the dashboard (a masked hint such as
`sk-…f3a1` is shown). Stored keys are injected into the environment of agents V/COMMAND launches,
never into checks. Standard library only.
"""
from __future__ import annotations

from pathlib import Path
import base64
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import threading
from typing import Any

SERVICE = "vcommand"
NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
KNOWN = {
    "ANTHROPIC_API_KEY": "Claude Code / Anthropic API (switches Claude Code to API billing)",
    "OPENAI_API_KEY": "Codex CLI / OpenAI",
    "OPENROUTER_API_KEY": "OpenRouter",
    "GEMINI_API_KEY": "Google Gemini",
    "DEEPSEEK_API_KEY": "DeepSeek",
    "GROQ_API_KEY": "Groq",
    "TELEGRAM_BOT_TOKEN": "Telegram bot for notifications and remote commands (never passed to agents)",
    "SLACK_WEBHOOK_URL": "Slack incoming webhook for notifications (never passed to agents)",
}
# Channel credentials stay with V/COMMAND: an agent that can read the bot token could approve its own
# risky commands through the remote.
NOT_FOR_AGENTS = {"TELEGRAM_BOT_TOKEN", "SLACK_WEBHOOK_URL"}
_LOCK = threading.Lock()


def config_dir() -> Path:
    if os.environ.get("VCOMMAND_HOME"):
        return Path(os.environ["VCOMMAND_HOME"])
    if platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "vcommand"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "vcommand"


def validate_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise ValueError("Secret names look like environment variables: A-Z, 0-9, _ (e.g. ANTHROPIC_API_KEY)")
    return name


def mask(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    prefix = value[:3] if value[:3].isascii() else ""
    return f"{prefix}…{value[-4:]}"


# ---------------------------------------------------------------- backends

class FileBackend:
    name = "file (0600, not encrypted)"
    encrypted = False

    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "secrets.json"

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _store(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def set(self, name: str, value: str) -> None:
        data = self._load()
        data[name] = self.encode(value)
        self._store(data)

    def get(self, name: str) -> str | None:
        raw = self._load().get(name)
        return None if raw is None else self.decode(raw)

    def delete(self, name: str) -> None:
        data = self._load()
        data.pop(name, None)
        self._store(data)

    def names(self) -> list[str]:
        return sorted(self._load())

    def encode(self, value: str) -> str:
        return value

    def decode(self, raw: str) -> str:
        return raw


class DpapiBackend(FileBackend):
    """Windows: values encrypted with DPAPI for the current user, stored in the same JSON file."""
    name = "Windows DPAPI (encrypted for your user)"
    encrypted = True

    def __init__(self, path: Path | None = None):
        super().__init__(path or config_dir() / "secrets.dpapi.json")

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _call(self, fn_name: str, data: bytes) -> bytes:
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32  # type: ignore[attr-defined]
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = self._Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = self._Blob()
        fn = getattr(crypt32, fn_name)
        ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))  # UI_FORBIDDEN
        if not ok:
            raise OSError(f"{fn_name} failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

    def encode(self, value: str) -> str:
        return base64.b64encode(self._call("CryptProtectData", value.encode("utf-8"))).decode("ascii")

    def decode(self, raw: str) -> str:
        return self._call("CryptUnprotectData", base64.b64decode(raw)).decode("utf-8")


class _IndexedBackend:
    """Keychains cannot list our entries cheaply; keep an index of names (never values)."""
    encrypted = True

    def __init__(self):
        self.index = config_dir() / "secrets-index.json"

    def names(self) -> list[str]:
        try:
            return sorted(json.loads(self.index.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return []

    def _index(self, name: str, present: bool) -> None:
        names = set(self.names())
        (names.add if present else names.discard)(name)
        self.index.parent.mkdir(parents=True, exist_ok=True)
        self.index.write_text(json.dumps(sorted(names)), encoding="utf-8")


class KeychainBackend(_IndexedBackend):
    name = "macOS Keychain"

    def set(self, name: str, value: str) -> None:
        proc = subprocess.run(["security", "add-generic-password", "-U", "-a", name, "-s", SERVICE, "-w", value],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise OSError(f"Keychain refused to store {name}: {proc.stderr.strip()[:200]}")
        self._index(name, True)

    def get(self, name: str) -> str | None:
        proc = subprocess.run(["security", "find-generic-password", "-a", name, "-s", SERVICE, "-w"],
                              capture_output=True, text=True)
        return proc.stdout.rstrip("\n") if proc.returncode == 0 else None

    def delete(self, name: str) -> None:
        subprocess.run(["security", "delete-generic-password", "-a", name, "-s", SERVICE], capture_output=True)
        self._index(name, False)


class SecretServiceBackend(_IndexedBackend):
    name = "Secret Service (secret-tool)"

    def set(self, name: str, value: str) -> None:
        proc = subprocess.run(["secret-tool", "store", f"--label=V/COMMAND {name}", "service", SERVICE, "key", name],
                              input=value, capture_output=True, text=True)
        if proc.returncode != 0:
            raise OSError(f"secret-tool refused to store {name}: {proc.stderr.strip()[:200]}")
        self._index(name, True)

    def get(self, name: str) -> str | None:
        proc = subprocess.run(["secret-tool", "lookup", "service", SERVICE, "key", name], capture_output=True, text=True)
        return proc.stdout if proc.returncode == 0 and proc.stdout else None

    def delete(self, name: str) -> None:
        subprocess.run(["secret-tool", "clear", "service", SERVICE, "key", name], capture_output=True)
        self._index(name, False)


def _secret_service_usable() -> bool:
    if not shutil.which("secret-tool") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return False
    probe = subprocess.run(["secret-tool", "search", "service", SERVICE], capture_output=True, timeout=5)
    return probe.returncode in (0, 1)


def backend():
    forced = os.environ.get("VCOMMAND_SECRETS_BACKEND")
    if forced == "file":
        return FileBackend()
    system = platform.system()
    if system == "Darwin" and shutil.which("security") and forced != "no-keychain":
        return KeychainBackend()
    if system == "Windows":
        return DpapiBackend()
    try:
        if system == "Linux" and _secret_service_usable():
            return SecretServiceBackend()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return FileBackend()


# ---------------------------------------------------------------- API

def set_secret(name: str, value: str) -> dict[str, Any]:
    validate_name(name)
    value = value.strip()
    if not value:
        raise ValueError("Empty secret value")
    with _LOCK:
        b = backend()
        b.set(name, value)
    return {"name": name, "hint": mask(value), "backend": b.name}


def get_secret(name: str) -> str | None:
    validate_name(name)
    return backend().get(name)


def delete_secret(name: str) -> None:
    validate_name(name)
    with _LOCK:
        backend().delete(name)


def list_secrets() -> list[dict[str, Any]]:
    b = backend()
    out = []
    for name in b.names():
        value = b.get(name)
        out.append({"name": name, "hint": mask(value) if value else "(missing in store)",
                    "label": KNOWN.get(name, ""), "in_environment": name in os.environ})
    return out


def describe_backend() -> dict[str, Any]:
    b = backend()
    return {"name": b.name, "encrypted": b.encrypted}


def secrets_env() -> dict[str, str]:
    """All stored secrets for agent processes. A variable already set in the environment wins."""
    b = backend()
    env = {}
    for name in b.names():
        if name in os.environ or name in NOT_FOR_AGENTS or name.startswith("VCMD_CHANNEL_"):
            continue
        value = b.get(name)
        if value:
            env[name] = value
    return env
