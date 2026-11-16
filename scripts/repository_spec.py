"""Licensed media and owner settings never enter git."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LICENSED = (".rom", ".adf", ".key", ".hdf", ".lha")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


@pytest.fixture(autouse=True)
def repository() -> None:
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git work tree")


class DescribeTrackedFiles:
    def should_track_no_firmware_disk_image_key_or_env_file(self) -> None:
        tracked = git("ls-files").stdout.splitlines()

        assert [path for path in tracked if path.lower().endswith(LICENSED)] == []
        assert [path for path in tracked if Path(path).name == ".env"] == []
        assert [path for path in tracked if path.startswith(("local/", "build/"))] == []

    @pytest.mark.parametrize(
        "path", [".env", "local/roms/kick13.rom", "local/roms/rom.key", "build/demo/demo.adf"]
    )
    def should_ignore_owner_settings_firmware_and_build_products(self, path: str) -> None:
        assert git("check-ignore", "--no-index", "-q", path).returncode == 0

    def should_track_the_example_settings_file(self) -> None:
        assert git("check-ignore", "--no-index", "-q", ".env.example").returncode == 1
