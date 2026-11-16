"""Check the native tools, Amiberry's isolation and a target's firmware without booting.

It reports paths. It returns nonzero when a tool is missing, when Amiberry
resolves a path outside the repository, or when the selected target's
Kickstart ROM is missing or differs from firmware.json.
"""

import argparse
import platform
import sys
from pathlib import Path

import amiberry
import firmware
import native

TOOLS = {
    "amiberry": "Amiberry, the Amiga emulator",
    "vasm": "vasm, the 68000 assembler (Motorola syntax)",
    "vlink": "vlink, the linker",
}


class Probe:
    """Gateway: find tools and ask Amiberry for the paths it resolves."""

    def tool(self, name: str) -> Path | None:
        return native.tool_path(name)

    def amiberry_paths(self, executable: Path, root: Path) -> dict[str, str]:
        emulator = amiberry.Amiberry(executable, root, platform.system())
        return amiberry.parse_dump(emulator.dump([], "--dump-paths"))


def check_tools(probe: Probe) -> list[str]:
    missing = []
    for name, purpose in TOOLS.items():
        path = probe.tool(name)
        if path:
            print(f"{name}: {path} ({purpose})")
        else:
            print(f"{name}: missing ({purpose}); run uv run python scripts/native.py")
            missing.append(name)
    return missing


def check_isolation(probe: Probe, root: Path) -> bool:
    executable = probe.tool("amiberry")
    if executable is None:
        return False
    paths = probe.amiberry_paths(executable, root)
    if "rom_path" not in paths and "home_dir" not in paths:
        print("Amiberry isolation: FAIL; --dump-paths printed no paths")
        return False
    outside = amiberry.outside_paths(paths, root)
    for key, value in outside.items():
        print(f"Amiberry isolation: FAIL; {key}={value} is outside {root}")
    if not outside:
        print(f"Amiberry isolation: {len(paths)} resolved paths are inside {root}")
    return not outside


def check_firmware(root: Path, target: str | None) -> bool:
    if target is None:
        print("Firmware NOT checked. Add --target a500 or --target a1200.")
        return True
    try:
        rom_id, path = firmware.installed(root, target)
    except (OSError, firmware.FirmwareError) as error:
        print(f"Firmware for {target}: FAIL\n{error}")
        return False
    title = firmware.load(root).roms[rom_id].title
    print(f"Firmware for {target}: {rom_id} verified ({title}) at {path}")
    return True


def main(
    argv: list[str] | None = None, root: Path = native.ROOT, probe: Probe | None = None
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("a500", "a1200"), help="also verify this target's ROM")
    options = parser.parse_args(argv)
    probe = probe or Probe()
    print(f"Python: {sys.executable}")
    missing = check_tools(probe)
    isolated = check_isolation(probe, root)
    firmware_ok = check_firmware(root, options.target)
    print("These checks do not boot the machine. Run scripts/amiga.py check on an example.")
    print("Read guidance/starter/toolchain.md and guidance/starter/setup.md to resolve a failure.")
    return 0 if not missing and isolated and firmware_ok else 1


if __name__ == "__main__":
    sys.exit(main())
