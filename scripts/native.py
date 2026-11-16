"""Install the pinned native tools into ignored `local/tools/`: Amiberry, vasm and vlink.

Every download is checked against a SHA-256 recorded here before anything
reads it. Amiberry comes from its GitHub release. vasm and vlink are built
from source with the host C compiler; their authors' download host stopped
serving the versioned archives in November 2026, so each archive also lists an
Internet Archive capture of the same file. The checksum, not the host, decides.

Set AMIBERRY, VASM or VLINK to use another executable.
"""

import argparse
import hashlib
import io
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path("local/tools")
USER_AGENT = "retro-explorer-amiga/0.1"

AMIBERRY_VERSION = "8.5.0"
AMIBERRY_RELEASE = (
    f"https://github.com/BlitterStudio/amiberry/releases/download/v{AMIBERRY_VERSION}/"
)
# From the release's SHA256SUMS asset.
AMIBERRY_ASSETS = {
    ("Darwin", "arm64"): (
        f"Amiberry-{AMIBERRY_VERSION}-macOS-universal.dmg",
        "002bb71af68a86a23c2779258248af71683c6a56caf74cf716e40081b5df9e7a",
    ),
    ("Linux", "x86_64"): (
        f"Amiberry-{AMIBERRY_VERSION}-x86_64.AppImage",
        "0677a18c570f837eabc1be28249f25f9ba97352598d6d50242ce9024d18dfb4f",
    ),
    ("Linux", "aarch64"): (
        f"Amiberry-{AMIBERRY_VERSION}-aarch64.AppImage",
        "2b9f623293edf34721f6dc81b8607bdec8f730e024c5e4f04341bcbb081c1910",
    ),
}
MAC_BINARY = Path("Amiberry.app/Contents/MacOS/Amiberry")

VARIABLES = {"amiberry": "AMIBERRY", "vasm": "VASM", "vlink": "VLINK"}


class SourceArchive(BaseModel):
    """A pinned source release that builds with its own Makefile."""

    model_config = ConfigDict(frozen=True)
    name: str
    version: str
    sha256: str
    urls: tuple[str, ...]
    make_args: tuple[str, ...]
    product: str


VASM = SourceArchive(
    name="vasm",
    version="2.0f",
    sha256="c84b2de1cbb87831795fe64a85c5d9a7002a766e3a7c30b0a2d7d5e99d878f49",
    urls=(
        "http://phoenix.owl.de/tags/vasm2_0f.tar.gz",
        "https://web.archive.org/web/20260801103915id_/http://phoenix.owl.de/tags/vasm2_0f.tar.gz",
    ),
    make_args=("CPU=m68k", "SYNTAX=mot"),
    product="vasmm68k_mot",
)
VLINK = SourceArchive(
    name="vlink",
    version="0.18a",
    sha256="8d151cdd30a4feb575a364e68810c2bc300fe1a7c074dbbee6fd1175a6c5bfae",
    urls=(
        "http://phoenix.owl.de/tags/vlink0_18a.tar.gz",
        "https://web.archive.org/web/20260903181732id_/http://sun.hasenbraten.de/vlink/release/vlink.tar.gz",
    ),
    make_args=(),
    product="vlink",
)
SOURCES = (VASM, VLINK)


class InstallError(RuntimeError):
    """A download, checksum or build step failed."""


class Downloads:
    """Gateway: fetch a URL's bytes."""

    def fetch(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read()


class Commands:
    """Gateway: run a host program and report its exit status and output."""

    def run(self, argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, cwd=cwd, check=False, capture_output=True, text=True)


def host() -> tuple[str, str]:
    return platform.system(), platform.machine()


def amiberry_asset(system: str, machine: str) -> tuple[str, str]:
    machine = {"amd64": "x86_64", "arm64": "arm64" if system == "Darwin" else "aarch64"}.get(
        machine, machine
    )
    try:
        return AMIBERRY_ASSETS[(system, machine)]
    except KeyError:
        raise InstallError(
            f"No Amiberry {AMIBERRY_VERSION} asset is pinned for {system} {machine}. "
            "Supported hosts: Apple Silicon macOS, Linux x86_64 and aarch64."
        ) from None


def checked(payload: bytes, sha256: str, label: str) -> bytes:
    found = hashlib.sha256(payload).hexdigest()
    if found != sha256:
        raise InstallError(f"{label}: SHA-256 {found}, but {sha256} is pinned")
    return payload


def fetch_pinned(urls: tuple[str, ...], sha256: str, downloads: Downloads) -> bytes:
    """The first download whose checksum matches. Every failure is reported."""
    failures = []
    for url in urls:
        try:
            return checked(downloads.fetch(url), sha256, url)
        except (OSError, InstallError) as error:
            failures.append(f"{url}: {error}")
    raise InstallError("No source supplied the pinned file:\n  " + "\n  ".join(failures))


def stray_members(names: list[str], top: str) -> list[str]:
    """Archive members that are not `top` or inside it."""
    return [name for name in names if name != top and not name.startswith(f"{top}/")]


def make_command(source: SourceArchive, jobs: int) -> list[str]:
    return ["make", f"-j{jobs}", "CC=cc", *source.make_args]


def install_dir(root: Path, name: str, version: str) -> Path:
    return root / TOOLS / name / version


def project_tool(root: Path, name: str) -> Path:
    """Where the installer puts a tool for this repository."""
    if name == "amiberry":
        folder = install_dir(root, "amiberry", AMIBERRY_VERSION)
        if host()[0] == "Darwin":
            return folder / MAC_BINARY
        return folder / amiberry_asset(*host())[0]
    source = VASM if name == "vasm" else VLINK
    return install_dir(root, source.name, source.version) / source.product


def tool_path(name: str, root: Path = ROOT, environ: Mapping[str, str] = os.environ) -> Path | None:
    """The override variable's executable, else this repository's installed tool."""
    override = environ.get(VARIABLES[name])
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() and os.access(path, os.X_OK) else None
    path = project_tool(root, name)
    return path if path.is_file() else None


def install_amiberry(root: Path, downloads: Downloads, commands: Commands) -> Path:
    target = project_tool(root, "amiberry")
    if target.is_file():
        return target
    name, sha256 = amiberry_asset(*host())
    payload = fetch_pinned((AMIBERRY_RELEASE + name,), sha256, downloads)
    folder = install_dir(root, "amiberry", AMIBERRY_VERSION)
    folder.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=folder.parent))
    try:
        unpacked = staging / AMIBERRY_VERSION
        unpacked.mkdir()
        if name.endswith(".dmg"):
            _unpack_dmg(payload, staging, unpacked, commands)
        else:
            image = unpacked / name
            image.write_bytes(payload)
            image.chmod(0o755)
        shutil.move(unpacked, folder)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def _unpack_dmg(payload: bytes, staging: Path, unpacked: Path, commands: Commands) -> None:
    image = staging / "amiberry.dmg"
    image.write_bytes(payload)
    mount = staging / "mount"
    mount.mkdir()
    attach = ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(image)]
    _require(commands.run(attach), "hdiutil attach")
    try:
        # ditto keeps the bundle's signature and extended attributes intact.
        copy = ["ditto", str(mount / "Amiberry.app"), str(unpacked / "Amiberry.app")]
        _require(commands.run(copy), "ditto")
    finally:
        commands.run(["hdiutil", "detach", str(mount)])


def install_source(
    root: Path, source: SourceArchive, downloads: Downloads, commands: Commands
) -> Path:
    target = install_dir(root, source.name, source.version) / source.product
    if target.is_file():
        return target
    payload = fetch_pinned(source.urls, source.sha256, downloads)
    target.parent.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=target.parent.parent))
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            stray = stray_members(archive.getnames(), source.name)
            if stray:
                raise InstallError(
                    f"{source.name} archive has members outside its folder: {stray[:3]}"
                )
            # The data filter refuses links out of the folder, devices and absolute paths.
            archive.extractall(staging / "src", filter="data")
        build = staging / "src" / source.name
        _require(
            commands.run(make_command(source, os.cpu_count() or 1), build), f"make {source.name}"
        )
        out = staging / source.version
        out.mkdir()
        shutil.copy2(build / source.product, out / source.product)
        shutil.move(out, target.parent)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def _require(result: subprocess.CompletedProcess[str], step: str) -> None:
    if result.returncode != 0:
        raise InstallError(f"{step} failed ({result.returncode}): {result.stderr[-2000:]}")


def install_all(
    root: Path = ROOT, downloads: Downloads | None = None, commands: Commands | None = None
) -> list[str]:
    downloads, commands = downloads or Downloads(), commands or Commands()
    paths = [install_amiberry(root, downloads, commands)]
    paths += [install_source(root, source, downloads, commands) for source in SOURCES]
    return [str(path) for path in paths]


def main(argv: list[str] | None = None, root: Path = ROOT, **gateways: object) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        for path in install_all(root, **gateways):  # type: ignore[arg-type]
            print(f"Installed: {path}")
    except (OSError, InstallError) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
