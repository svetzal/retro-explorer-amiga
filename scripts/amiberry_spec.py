"""Amiberry isolation and control-socket parsing."""

from pathlib import Path

import amiberry
import pytest


class DescribeSettings:
    def should_set_owned_keys_and_keep_amiberry_lines(self) -> None:
        existing = "rom_path=/Users/me/roms/\nwindow_x=40\nrom_path=/again/\n"

        merged = amiberry.merge_settings(
            existing, {"rom_path": "/repo/roms/", "plugins_dir": "/p/"}
        )

        assert merged == "rom_path=/repo/roms/\nwindow_x=40\nplugins_dir=/p/\n"

    @pytest.mark.parametrize(
        "system, folder",
        [("Darwin", "Library/Application Support/Amiberry"), ("Linux", ".config/amiberry")],
    )
    def should_write_the_private_settings_inside_the_repository(
        self, tmp_path: Path, system: str, folder: str
    ) -> None:
        home = amiberry.prepare_home(tmp_path, system)

        conf = (home / folder / "amiberry.conf").read_text()
        assert f"rom_path={tmp_path}/local/roms/" in conf
        assert home == tmp_path / "local/amiberry-home"

    def should_keep_the_settings_file_when_nothing_changes(self, tmp_path: Path) -> None:
        home = amiberry.prepare_home(tmp_path, "Linux")
        conf = home / ".config/amiberry/amiberry.conf"
        conf.write_text(conf.read_text() + "saved_by_amiberry=1\n")

        amiberry.prepare_home(tmp_path, "Linux")

        assert "saved_by_amiberry=1" in conf.read_text()


class DescribeEnvironment:
    def should_use_dummy_drivers_only_when_headless(self) -> None:
        headless = amiberry.environment(Path("/h"), True, {"PATH": "/bin"})
        window = amiberry.environment(Path("/h"), False, {"PATH": "/bin", "HOME": "/Users/me"})

        assert headless == {
            "SDL_VIDEODRIVER": "dummy",
            "SDL_AUDIODRIVER": "dummy",
            "PATH": "/bin",
            "HOME": "/h",
        }
        assert window == {"PATH": "/bin", "HOME": "/h"}

    def should_keep_a_driver_the_caller_chose(self) -> None:
        env = amiberry.environment(Path("/h"), True, {"SDL_AUDIODRIVER": "disk"})

        assert env["SDL_AUDIODRIVER"] == "disk"


class DescribeDumps:
    def should_parse_key_value_lines_and_skip_comments(self) -> None:
        text = "; no ROM inventory: x=y\nrom_path=/r/\ncpu_model=68000\nnot a pair\n"

        assert amiberry.parse_dump(text) == {"rom_path": "/r/", "cpu_model": "68000"}

    def should_list_resolved_paths_outside_the_repository(self, tmp_path: Path) -> None:
        paths = {
            "rom_path": f"{tmp_path}/local/roms/",
            "config_path": "/Users/someone/Amiberry/Configurations",
            "compiled_data_dir": "/usr/local/share/amiberry/data",
            "relative_paths": "0",
            "install_prefix": "",
        }

        outside = amiberry.outside_paths(paths, tmp_path)

        assert outside == {"config_path": "/Users/someone/Amiberry/Configurations"}


class DescribeReplies:
    def should_find_the_socket_this_run_opened(self) -> None:
        log = "Default socket in use, using instance 1\nIPC: Listening on /tmp/amiberry_1.sock\n"

        assert amiberry.socket_path(log) == "/tmp/amiberry_1.sock"
        assert amiberry.socket_path("starting") is None

    def should_read_a_named_field(self) -> None:
        reply = ["OK", "Paused=false", "Floppy0=/repo/build/x.adf"]

        assert amiberry.field(reply, "Floppy0") == "/repo/build/x.adf"
        assert amiberry.field(reply, "Floppy1") is None
