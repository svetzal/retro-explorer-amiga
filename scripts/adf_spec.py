"""Bootable floppy images, read back with amitools."""

from pathlib import Path

import adf
import pytest
from amitools.fs.ADFSVolume import ADFSVolume
from amitools.fs.blkdev.BlkDevFactory import BlkDevFactory
from amitools.fs.FSString import FSString


def read_disk(image: Path) -> tuple[str, dict[str, bytes], bytes]:
    device = BlkDevFactory().open(str(image), read_only=True)
    try:
        volume = ADFSVolume(device)
        volume.open()
        files = {name: volume.read_file(FSString(name)) for name in ("demo", "s/startup-sequence")}
        label = volume.get_volume_name().get_unicode()
        volume.close()
        boot = device.read_block(0) + device.read_block(1)
    finally:
        device.close()
    return label, files, boot


class DescribeBootableAdf:
    def should_write_a_bootable_ofs_disk_that_runs_the_program(self, tmp_path: Path) -> None:
        program = tmp_path / "demo"
        program.write_bytes(b"\x00\x00\x03\xf3program")

        image = adf.bootable_adf(tmp_path / "out/demo.adf", program, "demo")

        label, files, boot = read_disk(image)
        assert image.stat().st_size == 901120
        assert label == "demo"
        assert files == {"demo": program.read_bytes(), "s/startup-sequence": b"demo\n"}
        assert boot[:4] == b"DOS\x00"  # OFS
        assert not list(image.parent.glob(".*partial*"))

    @pytest.mark.parametrize("name", ["", "a" * 31, "dh0:demo", "+"])
    def should_refuse_a_name_the_disk_cannot_hold(self, tmp_path: Path, name: str) -> None:
        program = tmp_path / "demo"
        program.write_bytes(b"x")

        with pytest.raises(adf.DiskError):
            adf.bootable_adf(tmp_path / "x.adf", program, name)

    def should_report_an_xdftool_failure_and_leave_no_partial_file(self, tmp_path: Path) -> None:
        with pytest.raises(adf.DiskError, match="exit code"):
            adf.bootable_adf(tmp_path / "x.adf", tmp_path / "missing", "x")

        assert list(tmp_path.iterdir()) == []
