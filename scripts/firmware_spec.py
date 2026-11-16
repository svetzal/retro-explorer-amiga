"""Owner-supplied Kickstart ROMs: copy, verify and refuse mismatches."""

from collections.abc import Callable
from pathlib import Path

import firmware
import pytest
from conftest import TEST_KEY, TEST_ROM, encrypt

Prepare = Callable[..., dict[str, str]]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


class DescribeDecode:
    def should_return_a_plain_rom_unchanged(self) -> None:
        assert firmware.decode(TEST_ROM, None) == TEST_ROM

    def should_decrypt_an_amiga_forever_rom_with_its_key(self) -> None:
        assert firmware.decode(encrypt(TEST_ROM, TEST_KEY), TEST_KEY) == TEST_ROM

    def should_require_the_key_for_an_encrypted_rom(self) -> None:
        with pytest.raises(firmware.FirmwareError, match="rom.key"):
            firmware.decode(encrypt(TEST_ROM, TEST_KEY), None)


class DescribeProvision:
    @pytest.mark.parametrize("encrypted", [False, True])
    def should_copy_a_verified_rom_into_local(
        self, project: Path, owner_firmware: Prepare, encrypted: bool
    ) -> None:
        environ = owner_firmware(project, encrypted=encrypted)

        report = firmware.provision(project, "a500", environ)

        assert report == ["kick-test: verified Test Kickstart from TEST_PRODUCT_DIR"]
        assert firmware.installed(project, "a500") == (
            "kick-test",
            firmware.rom_path(project, "kick-test"),
        )
        assert firmware.key_path(project).is_file() is encrypted

    def should_name_the_variable_and_product_when_the_source_is_unset(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        owner_firmware(project)

        with pytest.raises(firmware.FirmwareError) as error:
            firmware.provision(project, "a500", {})

        message = str(error.value)
        assert "TEST_PRODUCT_DIR is not set" in message
        assert "set TEST_PRODUCT_DIR to the test folder (product: Test Product" in message
        assert not (project / "local").exists()

    def should_report_a_missing_file_in_the_source(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        environ = owner_firmware(project)
        (Path(environ["TEST_PRODUCT_DIR"]) / "kick.rom").unlink()

        with pytest.raises(firmware.FirmwareError, match="kick.rom does not exist"):
            firmware.provision(project, "a500", environ)

    def should_refuse_a_rom_that_differs_from_the_manifest(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        environ = owner_firmware(project)
        (Path(environ["TEST_PRODUCT_DIR"]) / "kick.rom").write_bytes(bytes(len(TEST_ROM)))

        with pytest.raises(firmware.FirmwareError, match="SHA-256"):
            firmware.provision(project, "a500", environ)

        assert not firmware.rom_path(project, "kick-test").exists()

    def should_refuse_a_rom_of_the_wrong_size(self, project: Path, owner_firmware: Prepare) -> None:
        environ = owner_firmware(project)
        (Path(environ["TEST_PRODUCT_DIR"]) / "kick.rom").write_bytes(b"short")

        with pytest.raises(firmware.FirmwareError, match="5 bytes"):
            firmware.provision(project, "a500", environ)

    def should_require_the_key_source_for_an_encrypted_rom(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        environ = owner_firmware(project, encrypted=True)
        (Path(environ["TEST_PRODUCT_DIR"]) / "rom.key").unlink()

        with pytest.raises(firmware.FirmwareError, match="needs rom.key"):
            firmware.provision(project, "a500", environ)

    def should_not_replace_a_different_installed_file(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        environ = owner_firmware(project)
        installed = firmware.rom_path(project, "kick-test")
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"owner's other file")

        with pytest.raises(firmware.FirmwareError, match="exists and differs"):
            firmware.provision(project, "a500", environ)

        assert installed.read_bytes() == b"owner's other file"

    def should_accept_a_second_run(self, project: Path, owner_firmware: Prepare) -> None:
        environ = owner_firmware(project, encrypted=True)
        firmware.provision(project, "a500", environ)

        assert firmware.provision(project, "a500", environ)[0].startswith("kick-test: verified")


class DescribeInstalled:
    def should_explain_how_to_install_a_missing_rom(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        owner_firmware(project)

        with pytest.raises(firmware.FirmwareError, match="--target a500 --firmware-only"):
            firmware.installed(project, "a500")

    def should_stop_at_a_damaged_installed_rom(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        firmware.provision(project, "a500", owner_firmware(project))
        firmware.rom_path(project, "kick-test").write_bytes(bytes(len(TEST_ROM)))

        with pytest.raises(firmware.FirmwareError, match="differs"):
            firmware.installed(project, "a500")

    def should_reject_an_unknown_target_or_rom(
        self, project: Path, owner_firmware: Prepare
    ) -> None:
        owner_firmware(project)

        with pytest.raises(firmware.FirmwareError, match="target 'a3000'"):
            firmware.installed(project, "a3000")
        with pytest.raises(firmware.FirmwareError, match="no ROM named"):
            firmware.first_installed(project, ["kick-none"], "a500")


class DescribeRepositoryManifest:
    def should_record_each_standard_target_with_known_roms(self) -> None:
        manifest = firmware.load(Path(__file__).resolve().parents[1])

        assert set(manifest.targets) == {"a500", "a1200"}
        for rom_ids in manifest.targets.values():
            assert all(rom_id in manifest.roms for rom_id in rom_ids)
