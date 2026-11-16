"""Run Amiberry inside the repository and drive it through its control socket.

Isolation: Amiberry reads a global `amiberry.conf` under the user's home.
Each run sets HOME to `local/amiberry-home/`, whose `amiberry.conf` points the
ROM, content and save paths into the repository. `--dump-paths` shows every
path that Amiberry resolved, and `outside_paths` lists any that escape.

Control: a running Amiberry (`--log`) prints `IPC: Listening on PATH`. Each
command is one line of tab-separated fields, and the reply starts with `OK`.
Facts measured with Amiberry 8.5.0 on Apple Silicon macOS are in
`guidance/starter/toolchain.md`.
"""

import os
import re
import socket
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

HOME = Path("local/amiberry-home")
LISTENING = re.compile(r"IPC: Listening on (\S+)")
# A compiled-in fallback that the macOS build does not use.
IGNORED_PATH_KEYS = frozenset({"compiled_data_dir"})


class EmulatorError(RuntimeError):
    """Amiberry did not start, did not answer, or refused a command."""


def settings_dir(home: Path, system: str) -> Path:
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Amiberry"
    return home / ".config" / "amiberry"


def owned_settings(home: Path, roms: Path) -> dict[str, str]:
    content = home / "Amiberry"
    return {
        "base_content_path": f"{content}/",
        "rom_path": f"{roms}/",
        "saveimage_dir": f"{content / 'SaveImages'}/",
        "plugins_dir": f"{content / 'Plugins'}/",
        "floppy_sounds_dir": f"{content / 'Data' / 'Floppy_Sounds'}/",
    }


def merge_settings(existing: str, owned: Mapping[str, str]) -> str:
    """Set the keys this repository owns and keep every line Amiberry saved itself."""
    placed: set[str] = set()
    merged = []
    for line in existing.splitlines():
        key = line.split("=", 1)[0]
        if key in owned:
            if key not in placed:
                merged.append(f"{key}={owned[key]}")
                placed.add(key)
        else:
            merged.append(line)
    merged += [f"{key}={value}" for key, value in owned.items() if key not in placed]
    return "\n".join(merged) + "\n"


def prepare_home(root: Path, system: str) -> Path:
    home = root / HOME
    conf = settings_dir(home, system) / "amiberry.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    (home / "Amiberry").mkdir(parents=True, exist_ok=True)
    existing = conf.read_text() if conf.exists() else ""
    wanted = merge_settings(existing, owned_settings(home, root / "local/roms"))
    if wanted != existing:
        conf.write_text(wanted)
    return home


def environment(home: Path, headless: bool, base: Mapping[str, str]) -> dict[str, str]:
    """A private HOME. Headless runs use SDL's dummy drivers unless the caller chose others."""
    env = dict(base) | {"HOME": str(home)}
    if headless:
        env = {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"} | env
    return env


def parse_dump(text: str) -> dict[str, str]:
    """`key=value` lines from `--dump-paths` or `--dump-config`."""
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key and " " not in key:
            values[key.strip()] = value.strip()
    return values


def outside_paths(paths: Mapping[str, str], root: Path) -> dict[str, str]:
    """Resolved absolute paths that are not inside the repository."""
    base = root.resolve()
    outside = {}
    for key, value in paths.items():
        if key in IGNORED_PATH_KEYS or not value.startswith("/"):
            continue
        if not Path(value).resolve().is_relative_to(base):
            outside[key] = value
    return outside


def socket_path(log: str) -> str | None:
    found = LISTENING.search(log)
    return found.group(1) if found else None


def field(reply: Sequence[str], name: str) -> str | None:
    """The value of `name=value` in a reply."""
    prefix = f"{name}="
    return next((item[len(prefix) :] for item in reply if item.startswith(prefix)), None)


class Amiberry:
    """Gateway: one Amiberry executable run with this repository's private home."""

    def __init__(self, executable: Path, root: Path, system: str) -> None:
        self.executable = executable
        self.home = prepare_home(root, system)

    def dump(self, args: Sequence[str], option: str) -> str:
        result = subprocess.run(
            [str(self.executable), *args, option],
            env=environment(self.home, True, os.environ),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return result.stdout + result.stderr

    def window(self, args: Sequence[str]) -> int:
        """Open a window for a person and wait until they close it."""
        command = [str(self.executable), *args, "-G"]
        env = environment(self.home, False, os.environ)
        return subprocess.run(command, env=env, check=False).returncode

    def start(self, args: Sequence[str], log: Path) -> "Session":
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("w")
        process = subprocess.Popen(
            [str(self.executable), "--log", *args, "-G"],
            env=environment(self.home, True, os.environ),
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        return Session(process, stream, log)


class Session:
    """Gateway: a headless Amiberry process this run started, and its control socket."""

    def __init__(self, process: subprocess.Popen[bytes], stream, log: Path) -> None:
        self._process = process
        self._stream = stream
        self.log = log
        self.socket: str | None = None

    def running(self) -> bool:
        return self._process.poll() is None

    def find_socket(self) -> bool:
        self.socket = socket_path(self.log.read_text(errors="replace"))
        return self.socket is not None

    def send(self, *fields: str) -> list[str]:
        if self.socket is None:
            raise EmulatorError("Amiberry has no control socket yet")
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(10)
            connection.connect(self.socket)
            connection.sendall(("\t".join(fields) + "\n").encode())
            reply = b""
            while not reply.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    break
                reply += chunk
        return reply.decode(errors="replace").rstrip("\n").split("\t")

    def stop(self) -> None:
        """QUIT through the socket; end the process only if that fails."""
        if self.running() and self.socket is not None:
            try:
                self.send("QUIT")
            except OSError:
                pass
        try:
            self._process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            self._process.wait(timeout=30)
        self._stream.close()
