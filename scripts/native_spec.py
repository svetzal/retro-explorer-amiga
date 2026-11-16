"""Pinned native tools: download checks, unpacking and discovery."""

import hashlib
import io
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock

import native
import pytest


def archive(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def source_for(payload: bytes) -> native.SourceArchive:
    return native.SourceArchive(
        name="tool",
        version="1.0",
        sha256=hashlib.sha256(payload).hexdigest(),
        urls=("https://first.example/tool.tar.gz", "https://second.example/tool.tar.gz"),
        make_args=("CPU=m68k",),
        product="tool-bin",
    )


def succeed(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    if argv[0] == "make" and cwd is not None:
        (cwd / "tool-bin").write_text("built")
    return subprocess.CompletedProcess(argv, 0, "", "")


@pytest.fixture
def downloads() -> Mock:
    return Mock(spec=native.Downloads)


@pytest.fixture
def commands() -> Mock:
    gateway = Mock(spec=native.Commands)
    gateway.run.side_effect = succeed
    return gateway


class DescribeFetchPinned:
    def should_fall_back_to_the_next_source_when_the_first_fails(self, downloads: Mock) -> None:
        downloads.fetch.side_effect = [OSError("404"), b"right"]

        payload = native.fetch_pinned(("a", "b"), hashlib.sha256(b"right").hexdigest(), downloads)

        assert payload == b"right"

    def should_refuse_bytes_that_differ_from_the_pin(self, downloads: Mock) -> None:
        downloads.fetch.return_value = b"wrong"

        with pytest.raises(native.InstallError, match="a: SHA-256"):
            native.fetch_pinned(("a",), hashlib.sha256(b"right").hexdigest(), downloads)


class DescribeAmiberryAsset:
    @pytest.mark.parametrize(
        "system, machine, name",
        [
            ("Darwin", "arm64", "Amiberry-8.5.0-macOS-universal.dmg"),
            ("Linux", "x86_64", "Amiberry-8.5.0-x86_64.AppImage"),
            ("Linux", "amd64", "Amiberry-8.5.0-x86_64.AppImage"),
            ("Linux", "arm64", "Amiberry-8.5.0-aarch64.AppImage"),
        ],
    )
    def should_pick_the_pinned_asset_for_the_host(
        self, system: str, machine: str, name: str
    ) -> None:
        assert native.amiberry_asset(system, machine)[0] == name

    def should_refuse_an_intel_mac(self) -> None:
        with pytest.raises(native.InstallError, match="Apple Silicon"):
            native.amiberry_asset("Darwin", "x86_64")


class DescribeInstallSource:
    def should_build_and_install_the_product(
        self, tmp_path: Path, downloads: Mock, commands: Mock
    ) -> None:
        payload = archive({"tool/Makefile": b"all:\n"})
        downloads.fetch.return_value = payload

        path = native.install_source(tmp_path, source_for(payload), downloads, commands)

        assert path == tmp_path / "local/tools/tool/1.0/tool-bin"
        assert path.read_text() == "built"
        make = commands.run.call_args.args[0]
        assert make[0] == "make" and "CPU=m68k" in make

    def should_reuse_an_installed_product(
        self, tmp_path: Path, downloads: Mock, commands: Mock
    ) -> None:
        installed = tmp_path / "local/tools/tool/1.0/tool-bin"
        installed.parent.mkdir(parents=True)
        installed.write_text("old")

        assert native.install_source(tmp_path, source_for(b""), downloads, commands) == installed
        downloads.fetch.assert_not_called()

    def should_refuse_members_outside_the_top_folder(
        self, tmp_path: Path, downloads: Mock, commands: Mock
    ) -> None:
        payload = archive({"tool/Makefile": b"", "elsewhere/x": b""})
        downloads.fetch.return_value = payload

        with pytest.raises(native.InstallError, match="outside its folder"):
            native.install_source(tmp_path, source_for(payload), downloads, commands)

        assert not (tmp_path / "local/tools/tool/1.0").exists()

    def should_report_a_failed_build(self, tmp_path: Path, downloads: Mock, commands: Mock) -> None:
        payload = archive({"tool/Makefile": b""})
        downloads.fetch.return_value = payload
        commands.run.side_effect = None
        commands.run.return_value = subprocess.CompletedProcess([], 2, "", "no compiler")

        with pytest.raises(native.InstallError, match="no compiler"):
            native.install_source(tmp_path, source_for(payload), downloads, commands)


class DescribeInstallAmiberry:
    def should_copy_the_app_out_of_the_disk_image_on_macos(
        self, tmp_path: Path, downloads: Mock, commands: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(native, "host", lambda: ("Darwin", "arm64"))
        monkeypatch.setitem(
            native.AMIBERRY_ASSETS,
            ("Darwin", "arm64"),
            ("a.dmg", hashlib.sha256(b"dmg").hexdigest()),
        )
        downloads.fetch.return_value = b"dmg"

        def ditto(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
            if argv[0] == "ditto":
                binary = Path(argv[2]) / "Contents/MacOS/Amiberry"
                binary.parent.mkdir(parents=True)
                binary.write_text("app")
            return subprocess.CompletedProcess(argv, 0, "", "")

        commands.run.side_effect = ditto

        path = native.install_amiberry(tmp_path, downloads, commands)

        assert path.read_text() == "app"
        assert [call.args[0][0:2] for call in commands.run.call_args_list][-1] == [
            "hdiutil",
            "detach",
        ]

    def should_keep_an_appimage_executable_on_linux(
        self, tmp_path: Path, downloads: Mock, commands: Mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(native, "host", lambda: ("Linux", "x86_64"))
        monkeypatch.setitem(
            native.AMIBERRY_ASSETS,
            ("Linux", "x86_64"),
            ("a.AppImage", hashlib.sha256(b"elf").hexdigest()),
        )
        downloads.fetch.return_value = b"elf"

        path = native.install_amiberry(tmp_path, downloads, commands)

        assert path.name == "a.AppImage" and path.stat().st_mode & 0o100


class DescribeToolPath:
    def should_prefer_an_executable_override(self, tmp_path: Path) -> None:
        tool = tmp_path / "vasm"
        tool.write_text("")
        tool.chmod(0o755)

        assert native.tool_path("vasm", tmp_path, {"VASM": str(tool)}) == tool

    def should_report_a_missing_override_or_install(self, tmp_path: Path) -> None:
        assert native.tool_path("vasm", tmp_path, {"VASM": str(tmp_path / "none")}) is None
        assert native.tool_path("vlink", tmp_path, {}) is None


class DescribeMain:
    def should_report_a_failure_without_a_traceback(
        self, tmp_path: Path, downloads: Mock, commands: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        downloads.fetch.side_effect = OSError("offline")

        assert native.main([], tmp_path, downloads=downloads, commands=commands) == 1
        assert "offline" in capsys.readouterr().err
