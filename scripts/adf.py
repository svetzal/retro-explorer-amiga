"""Write a bootable OFS floppy image whose startup-sequence runs one program.

The image uses the original file system (OFS) and the Kickstart 1.x boot
block, which Kickstart 1.3 needs. Kickstart 3.1 and 3.2 boot the same image
(measured with Amiberry 8.5.0; see guidance/starter/toolchain.md).
amitools' xdftool builds the whole disk in one pass.
"""

import tempfile
from pathlib import Path

from amitools.tools import xdftool

DD_SIZE = "880Ki"
BOOT_CODE = "boot1x"
STARTUP = "s/startup-sequence"
MAX_NAME = 30
SEPARATOR = "+"


class DiskError(ValueError):
    """The disk cannot hold a name, or xdftool failed."""


def check_name(name: str, what: str) -> str:
    if not name or len(name) > MAX_NAME:
        raise DiskError(f"{what} {name!r} must be 1 to {MAX_NAME} characters")
    if any(character in name for character in ":/") or name == SEPARATOR:
        raise DiskError(f"{what} {name!r} may not contain ':' or '/', or be {SEPARATOR!r}")
    return name


def xdftool_args(image: Path, program: Path, label: str, startup: Path) -> list[str]:
    steps = [
        ["create", f"size={DD_SIZE}"],
        ["format", check_name(label, "volume label"), "ofs"],
        ["boot", "install", BOOT_CODE],
        ["write", str(program), check_name(program.name, "file name")],
        ["makedir", "s"],
        ["write", str(startup), STARTUP],
    ]
    args = ["-f", "-s", SEPARATOR, str(image)]
    for index, step in enumerate(steps):
        args += ([SEPARATOR] if index else []) + step
    return args


def bootable_adf(image: Path, program: Path, label: str) -> Path:
    """Write `image` so that the machine boots and runs `program` from the root folder."""
    image.parent.mkdir(parents=True, exist_ok=True)
    # xdftool picks the image type from the suffix, so the partial file keeps `.adf`.
    partial = image.with_name(f".{image.stem}.partial.adf")
    with tempfile.TemporaryDirectory(prefix="amiga-adf-") as scratch:
        startup = Path(scratch) / "startup-sequence"
        startup.write_text(f"{program.name}\n")
        code = xdftool.main(xdftool_args(partial, program, label, startup))
    if code != 0:
        partial.unlink(missing_ok=True)
        raise DiskError(f"xdftool failed with exit code {code}")
    partial.replace(image)
    return image
