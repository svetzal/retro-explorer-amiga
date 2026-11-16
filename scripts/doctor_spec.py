"""The health check: tools, Amiberry isolation and firmware, without a boot."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import doctor
import firmware
import pytest


@pytest.fixture
def probe(tmp_path: Path) -> Mock:
    gateway = Mock(spec=doctor.Probe)
    gateway.tool.side_effect = lambda name: tmp_path / name
    gateway.amiberry_paths.return_value = {"rom_path": f"{tmp_path}/local/roms/"}
    return gateway


class DescribeDoctor:
    def should_pass_with_tools_isolation_and_verified_firmware(
        self,
        tmp_path: Path,
        probe: Mock,
        owner_firmware: Callable[[Path], dict[str, str]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        firmware.provision(tmp_path, "a500", owner_firmware(tmp_path))

        assert doctor.main(["--target", "a500"], tmp_path, probe) == 0

        output = capsys.readouterr().out
        assert "Firmware for a500: kick-test verified (Test Kickstart)" in output
        assert "do not boot the machine" in output

    def should_fail_and_say_how_to_install_missing_firmware(
        self,
        tmp_path: Path,
        probe: Mock,
        owner_firmware: Callable[[Path], dict[str, str]],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        owner_firmware(tmp_path)

        assert doctor.main(["--target", "a500"], tmp_path, probe) == 1

        assert "set TEST_PRODUCT_DIR" in capsys.readouterr().out

    def should_say_firmware_was_not_checked_without_a_target(
        self, tmp_path: Path, probe: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert doctor.main([], tmp_path, probe) == 0

        assert "Firmware NOT checked" in capsys.readouterr().out

    def should_fail_when_a_tool_is_missing(
        self, tmp_path: Path, probe: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        probe.tool.side_effect = lambda name: None

        assert doctor.main([], tmp_path, probe) == 1

        assert "amiberry: missing" in capsys.readouterr().out

    def should_fail_when_amiberry_resolves_a_path_outside_the_repository(
        self, tmp_path: Path, probe: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        probe.amiberry_paths.return_value = {"rom_path": "/Users/someone/Amiga/roms/"}

        assert doctor.main([], tmp_path, probe) == 1

        assert "rom_path=/Users/someone/Amiga/roms/ is outside" in capsys.readouterr().out

    def should_fail_when_amiberry_prints_no_paths(
        self, tmp_path: Path, probe: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        probe.amiberry_paths.return_value = {}

        assert doctor.main([], tmp_path, probe) == 1

        assert "printed no paths" in capsys.readouterr().out
