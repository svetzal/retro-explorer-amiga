"""The project tool: settings, the checkpoint protocol, comparisons and the real checks."""

import json
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import amiberry
import amiga
import firmware
import native
import numpy as np
import pytest
from PIL import Image

REPOSITORY = Path(__file__).resolve().parents[1]
FIRST_SCREEN = REPOSITORY / "examples/first-screen"
TARGET_TABLE = """
[targets.a500]
model = "A500"
kickstart = ["kick-test"]
video = "pal"
cpu = "68000"
chipset = "ocs"
chip_kib = 512
slow_kib = 512
fast_kib = 0
"""
SETTINGS = (
    TARGET_TABLE
    + """
[variants.broken]
defines = ["BROKEN"]
control = true

[check]
checkpoint = 2
seconds = 5
memory = { list = { at = "data", size = 6 }, fixed = { at = 0x200, offset = 4, size = 4 } }
"""
)
ROM_CONFIG = {
    "cpu_model": "68000",
    "chipset": "ocs",
    "chipmem_size": "1",
    "bogomem_size": "2",
    "fastmem_size": "0",
    "ntsc": "false",
}


def write_project(folder: Path, settings: str = SETTINGS) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "amiga.toml").write_text(settings)
    (folder / "main.s").write_text("        rts\n")
    return folder


class SteppingClock(amiga.Clock):
    """A simulated clock that advances only when the code under test waits."""

    def __init__(self) -> None:
        self.time = 0.0

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.time += seconds


class FakeMachine:
    """Replies like Amiberry's socket for a program that reaches its checkpoint."""

    def __init__(self, disk: Path, reach_after: int | None = 3, initial_magic: int = 0) -> None:
        self.disk = disk
        self.reach_after = reach_after
        self.memory = {0x100: initial_magic, 0x104: 0, 0x108: 0}
        self.polls = 0
        self.commands: list[str] = []

    def send(self, *fields: str) -> list[str]:
        self.commands.append(fields[0])
        handler = getattr(self, f"_{fields[0].lower()}", None)
        return handler(*fields[1:]) if handler else ["OK"]

    def _get_status(self) -> list[str]:
        return ["OK", "Paused=false", f"Floppy0={self.disk}"]

    def _read_mem(self, address: str, width: str) -> list[str]:
        address_value = int(address)
        if address_value == 0x100:
            self.polls += 1
            if self.reach_after is not None and self.polls > self.reach_after:
                self.memory |= {0x100: amiga.MAGIC, 0x104: 2, 0x108: 0x1000}
        stored = self.memory.get(address_value, 0x01020304 + address_value)
        return ["OK", str(stored)]

    def _get_custom_regs(self) -> list[str]:
        return ["OK", "DMACON=0280", "dma_copper=1", "COP1LC=00001000"]

    def _screenshot(self, path: str) -> list[str]:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.zeros((576, 752, 3), dtype=np.uint8)).save(path)
        return ["OK", path]


def session_for(machine: FakeMachine, tmp_path: Path) -> Mock:
    session = Mock(spec=amiberry.Session)
    session.socket = None
    session.log = tmp_path / "amiberry.log"
    session.running.return_value = True
    session.find_socket.return_value = True
    session.send.side_effect = machine.send
    return session


@pytest.fixture
def disk(tmp_path: Path) -> Path:
    path = tmp_path / "demo.adf"
    path.write_bytes(b"disk")
    return path


@pytest.fixture
def check() -> amiga.Check:
    return amiga.Check(
        checkpoint=2,
        seconds=5,
        memory={"list": amiga.Region(at="data", size=6), "fixed": amiga.Region(at=0x200, size=4)},
    )


class DescribeSettings:
    def should_load_targets_variants_and_check(self, tmp_path: Path) -> None:
        project = amiga.load_project(write_project(tmp_path / "demo"))

        assert project.name == "demo"
        assert project.settings.targets["a500"].chip_kib == 512
        assert project.settings.variants["broken"].control
        assert project.settings.check.memory["fixed"].offset == 4

    @pytest.mark.parametrize(
        "settings, message",
        [
            ("not toml [", "amiga.toml"),
            (TARGET_TABLE.replace("chip_kib = 512", "chip_kib = 100"), "multiple"),
            (TARGET_TABLE + "[variants.x]\ntargets = ['a1200']\n", "unknown targets"),
            ('source = "main.s"\n', "targets"),
        ],
    )
    def should_reject_invalid_settings(self, tmp_path: Path, settings: str, message: str) -> None:
        with pytest.raises(amiga.ProjectError, match=message):
            amiga.load_project(write_project(tmp_path / "demo", settings))

    def should_reject_a_missing_folder(self, tmp_path: Path) -> None:
        with pytest.raises(amiga.ProjectError):
            amiga.load_project(tmp_path / "none")


class DescribeRuns:
    @pytest.fixture
    def project(self, tmp_path: Path) -> amiga.Project:
        table_b = TARGET_TABLE.replace("targets.a500", "targets.b")
        settings = TARGET_TABLE + table_b + "[variants.only-b]\ntargets = ['b']\n"
        return amiga.load_project(write_project(tmp_path / "demo", settings))

    def should_use_every_target_by_default(self, project: amiga.Project) -> None:
        assert amiga.runs(project, None, "") == ["a500", "b"]

    def should_use_the_targets_a_variant_allows(self, project: amiga.Project) -> None:
        assert amiga.runs(project, None, "only-b") == ["b"]

    def should_refuse_a_target_the_variant_does_not_allow(self, project: amiga.Project) -> None:
        with pytest.raises(amiga.ProjectError, match="not one of"):
            amiga.runs(project, "a500", "only-b")

    def should_refuse_an_unknown_variant(self, project: amiga.Project) -> None:
        with pytest.raises(amiga.ProjectError, match="unknown variant"):
            amiga.runs(project, None, "none")


class DescribeCommandLines:
    def should_assemble_with_the_variant_defines_for_kickstart_1(self, tmp_path: Path) -> None:
        project = amiga.load_project(write_project(tmp_path / "demo"))

        args = amiga.vasm_args(Path("/v"), project, "broken", Path("/out"))

        assert args[:6] == ["/v", "-quiet", "-m68000", "-Fhunkexe", "-kick1hunks", "-nosym"]
        assert "-DBROKEN=1" in args
        assert args[-1] == str(project.folder / "main.s")

    def should_give_amiberry_the_target_table(self, tmp_path: Path) -> None:
        target = amiga.load_project(write_project(tmp_path / "demo")).settings.targets["a500"]

        args = amiga.amiberry_args(target, Path("/r.rom"), Path("/d.adf"))

        assert args[:6] == ["--model", "A500", "-r", "/r.rom", "-0", "/d.adf"]
        assert [args[i + 1] for i, a in enumerate(args) if a == "-s"] == [
            "ntsc=false",
            "cpu_model=68000",
            "chipset=ocs",
            "chipmem_size=1",
            "bogomem_size=2",
            "fastmem_size=0",
        ]


class DescribeConfiguration:
    @pytest.fixture
    def target(self, tmp_path: Path) -> amiga.Target:
        return amiga.load_project(write_project(tmp_path / "demo")).settings.targets["a500"]

    def should_accept_a_rom_shown_relative_to_the_rom_path(self, target: amiga.Target) -> None:
        config = ROM_CONFIG | {"kickstart_rom_file": "k.rom", "amiberry.rom_path": "/repo/roms/"}

        assert amiga.configuration_differences(target, Path("/repo/roms/k.rom"), config) == []

    def should_report_each_setting_amiberry_resolved_differently(
        self, target: amiga.Target
    ) -> None:
        config = ROM_CONFIG | {"chipset": "aga", "kickstart_rom_file": "/other.rom"}

        differences = amiga.configuration_differences(target, Path("/repo/k.rom"), config)

        assert differences == [
            "chipset=aga (table: ocs)",
            "kickstart_rom_file=/other.rom (table: /repo/k.rom)",
        ]


class DescribeObserve:
    def should_pause_at_the_checkpoint_and_record_memory_registers_and_screen(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        machine = FakeMachine(disk)

        observation = amiga.observe(
            session_for(machine, tmp_path), disk, check, tmp_path, SteppingClock()
        )

        assert observation.first_magic == 0
        assert observation.data == 0x1000
        assert (
            observation.memory["list"]
            == (0x01020304 + 0x1000).to_bytes(4) + (0x01020304 + 0x1004).to_bytes(4)[:2]
        )
        assert observation.registers["COP1LC"] == "00001000"
        assert observation.screenshot.is_file()
        assert machine.commands.index("PAUSE") < machine.commands.index("GET_CUSTOM_REGS")
        assert machine.commands[0:3] == ["GET_STATUS", "READ_MEM", "SET_WARP"]

    def should_refuse_a_magic_that_was_present_before_the_program_ran(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        session = session_for(FakeMachine(disk, initial_magic=amiga.MAGIC), tmp_path)

        with pytest.raises(amiberry.EmulatorError, match="present before"):
            amiga.observe(session, disk, check, tmp_path, SteppingClock())

        session.stop.assert_called_once()

    def should_fail_with_a_screenshot_when_the_checkpoint_never_comes(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        machine = FakeMachine(disk, reach_after=None)

        with pytest.raises(amiberry.EmulatorError, match="checkpoint 2 was not reached within 5 s"):
            amiga.observe(session_for(machine, tmp_path), disk, check, tmp_path, SteppingClock())

        assert (tmp_path / "timeout.png").is_file()

    def should_fail_when_amiberry_exits(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        session = session_for(FakeMachine(disk), tmp_path)
        session.running.side_effect = [True, False]

        with pytest.raises(amiberry.EmulatorError, match="exited before checkpoint 2"):
            amiga.observe(session, disk, check, tmp_path, SteppingClock())

    def should_fail_when_no_socket_opens(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        session = session_for(FakeMachine(disk), tmp_path)
        session.find_socket.return_value = False

        with pytest.raises(amiberry.EmulatorError, match="no control socket"):
            amiga.observe(session, disk, check, tmp_path, SteppingClock())

    def should_retry_until_the_socket_accepts(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        machine = FakeMachine(disk)
        session = session_for(machine, tmp_path)
        replies = iter([ConnectionRefusedError()])

        def refuse_once(*fields: str) -> list[str]:
            failure = next(replies, None)
            if failure:
                raise failure
            return machine.send(*fields)

        session.send.side_effect = refuse_once

        assert amiga.observe(session, disk, check, tmp_path, SteppingClock()).checkpoint == 2

    def should_leave_an_emulator_that_reports_another_disk(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        session = session_for(FakeMachine(tmp_path / "theirs.adf"), tmp_path)
        session.socket = "/tmp/theirs.sock"

        def found() -> bool:
            session.socket = "/tmp/theirs.sock"
            return True

        session.find_socket.side_effect = found

        with pytest.raises(amiberry.EmulatorError, match="not this run's"):
            amiga.observe(session, disk, check, tmp_path, SteppingClock())

        assert session.socket is None

    def should_report_a_refused_memory_read(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        machine = FakeMachine(disk)
        machine._read_mem = lambda address, width: ["ERROR", "bad address"]

        with pytest.raises(amiberry.EmulatorError, match="READ_MEM 0x100 failed"):
            amiga.observe(session_for(machine, tmp_path), disk, check, tmp_path, SteppingClock())

    def should_report_a_failed_screenshot(
        self, tmp_path: Path, disk: Path, check: amiga.Check
    ) -> None:
        machine = FakeMachine(disk)
        machine._screenshot = lambda path: ["ERROR", "no display"]

        with pytest.raises(amiberry.EmulatorError, match="SCREENSHOT failed"):
            amiga.observe(session_for(machine, tmp_path), disk, check, tmp_path, SteppingClock())


class DescribeComparisons:
    def should_report_the_first_differing_byte(self) -> None:
        result = amiga.compare_memory({"a": b"\x01\x02", "b": b"x"}, {"a": b"\x01\x03"})

        assert result.status == "FAIL"
        assert (
            result.detail
            == "a: byte 1 is 0x03, expected 0x02; b: not read; declare it under [check.memory]"
        )

    def should_pass_matching_memory_and_registers(self) -> None:
        assert amiga.compare_memory({"a": b"\x01"}, {"a": b"\x01\x02"}).status == "PASS"
        assert (
            amiga.compare_registers({"COP1LC": "0000abcd"}, {"COP1LC": "0000ABCD"}).status == "PASS"
        )

    def should_report_a_differing_register(self) -> None:
        result = amiga.compare_registers({"dma_copper": "1"}, {"dma_copper": "0"})

        assert (result.status, result.detail) == ("FAIL", "dma_copper=0 (expected 1)")

    def should_compare_both_rows_of_each_display_line(self) -> None:
        image = np.zeros((20, 40, 3), dtype=np.uint8)
        image[0:2] = (0, 0, 255)  # line 25 in a PAL capture
        image[3, 20] = (255, 255, 255)  # second row of line 26

        assert amiga.compare_lines({25: (0, 0, 255)}, image, "pal").status == "PASS"
        result = amiga.compare_lines({26: (0, 0, 0)}, image, "pal")
        assert (result.status, result.detail.split(" (")[0]) == ("FAIL", "line 26: 1 pixels differ")

    def should_refuse_a_line_outside_the_capture(self) -> None:
        image = np.zeros((4, 40, 3), dtype=np.uint8)

        result = amiga.compare_lines({19: (0, 0, 0), 23: (0, 0, 0)}, image, "ntsc")

        assert result.detail == (
            "line 19 is outside the 4-row capture; line 23 is outside the 4-row capture"
        )

    def should_pass_only_the_arguments_a_model_names(self) -> None:
        def model(data: int, video: str) -> tuple[int, str]:
            return data, video

        assert amiga.call_model(model, data=1, video="pal", target="a500") == (1, "pal")

    def should_compare_every_kind_the_model_supplies(self, tmp_path: Path) -> None:
        screenshot = tmp_path / "screen.png"
        Image.fromarray(np.zeros((576, 752, 3), dtype=np.uint8)).save(screenshot)
        observation = amiga.Observation(
            first_magic=0,
            checkpoint=1,
            data=0x40,
            seconds=1.0,
            memory={"m": b"\x00"},
            registers={"COP1LC": "00000040"},
            screenshot=screenshot,
        )
        model = SimpleNamespace(
            expected_memory=lambda: {"m": b"\x00"},
            expected_registers=lambda data: {"COP1LC": f"{data:08X}"},
            expected_lines=lambda: {100: (0, 0, 0)},
        )

        results = amiga.compare(model, observation, target="a500", variant="", video="pal")

        assert [(r.kind, r.status) for r in results] == [
            ("memory", "PASS"),
            ("registers", "PASS"),
            ("screen", "PASS"),
        ]
        assert amiga.compare(None, observation)[0].status == "NOT CHECKED"


class DescribeExpectedModel:
    def should_load_a_folder_model(self, tmp_path: Path) -> None:
        (tmp_path / "expected.py").write_text("def expected_memory():\n    return {}\n")

        assert amiga.load_expected(tmp_path).expected_memory() == {}
        assert amiga.load_expected(tmp_path / "none") is None


@pytest.fixture
def owned_root(
    tmp_path: Path,
    owner_firmware: Callable[[Path], dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """A repository root with a verified test ROM, used in place of this repository."""
    root = tmp_path / "root"
    root.mkdir()
    firmware.provision(root, "a500", owner_firmware(root))
    monkeypatch.setattr(amiga, "ROOT", root)
    return root


def host_for(
    root: Path, machine_for: Callable[[Path], FakeMachine], config: dict[str, str]
) -> Mock:
    """A Host whose assembler writes a program and whose emulator answers like Amiberry."""
    host = Mock(spec=amiga.Host)
    host.tool.side_effect = lambda name: Path(f"/tools/{name}")

    def assemble(argv: list[str]) -> subprocess.CompletedProcess[str]:
        Path(argv[argv.index("-o") + 1]).write_bytes(b"\x00\x00\x03\xf3")
        return subprocess.CompletedProcess(argv, 0, "", "")

    host.assemble.side_effect = assemble
    emulator = Mock(spec=amiberry.Amiberry)
    rom_config = config | {"amiberry.rom_path": str(root / "local/roms")}
    emulator.dump.return_value = "\n".join(f"{k}={v}" for k, v in rom_config.items())

    def start(args: list[str], log: Path) -> Mock:
        disk = Path(args[args.index("-0") + 1])
        return session_for(machine_for(disk), log.parent)

    emulator.start.side_effect = start
    host.emulator.return_value = emulator
    host.clock.return_value = SteppingClock()
    return host


class DescribeCommands:
    @pytest.fixture
    def project(self, owned_root: Path) -> Path:
        folder = write_project(owned_root / "demo")
        (folder / "expected.py").write_text(
            "def expected_registers(data):\n    return {'COP1LC': f'{data:08X}'}\n"
        )
        return folder

    def should_check_a_target_and_save_its_evidence(
        self, owned_root: Path, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = host_for(
            owned_root, FakeMachine, ROM_CONFIG | {"kickstart_rom_file": "kick-test.rom"}
        )

        assert amiga.main(["check", str(project)], host) == 0

        output = capsys.readouterr().out
        assert "execution: PASS checkpoint 2 reached" in output
        assert "registers: PASS COP1LC=00001000" in output
        assert "visual: NOT CHECKED not inspected by a person" in output
        report = json.loads((owned_root / "build/demo/a500/report.json").read_text())
        assert report["observation"]["data"] == 0x1000
        assert (owned_root / "build/demo/a500/list.bin").stat().st_size == 6

    def should_stop_at_a_configuration_that_differs_from_the_table(
        self, owned_root: Path, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = host_for(owned_root, FakeMachine, ROM_CONFIG | {"cpu_model": "68020"})

        assert amiga.main(["check", str(project)], host) == 1

        assert "configuration: FAIL cpu_model=68020 (table: 68000)" in capsys.readouterr().out
        host.emulator.return_value.start.assert_not_called()

    def should_label_a_failing_control(
        self, owned_root: Path, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = host_for(
            owned_root,
            lambda disk: FakeMachine(disk, reach_after=None),
            ROM_CONFIG | {"kickstart_rom_file": "kick-test.rom"},
        )

        assert amiga.main(["check", str(project), "--variant", "broken"], host) == 1

        output = capsys.readouterr().out
        assert "execution: FAIL checkpoint 2 was not reached" in output
        assert "FAIL is the required result" in output

    def should_report_missing_firmware_as_its_own_evidence(
        self, owned_root: Path, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        firmware.rom_path(owned_root, "kick-test").unlink()
        host = host_for(owned_root, FakeMachine, ROM_CONFIG)

        assert amiga.main(["snapshot", str(project)], host) == 1

        assert "firmware: FAIL No Kickstart ROM for a500" in capsys.readouterr().out

    def should_save_a_snapshot_without_comparing(
        self, owned_root: Path, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = host_for(
            owned_root, FakeMachine, ROM_CONFIG | {"kickstart_rom_file": "kick-test.rom"}
        )

        assert amiga.main(["snapshot", str(project)], host) == 0

        output = capsys.readouterr().out
        assert "snapshot: SAVED" in output and "registers:" not in output

    def should_print_the_built_disk(
        self, owned_root: Path, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = host_for(owned_root, FakeMachine, ROM_CONFIG)

        assert amiga.main(["build", str(project)], host) == 0

        assert capsys.readouterr().out.strip() == str(owned_root / "build/demo/demo.adf")

    def should_open_a_window_with_the_verified_rom(self, owned_root: Path, project: Path) -> None:
        host = host_for(owned_root, FakeMachine, ROM_CONFIG)
        host.emulator.return_value.window.return_value = 0

        assert amiga.main(["run", str(project)], host) == 0

        args = host.emulator.return_value.window.call_args.args[0]
        assert args[args.index("-r") + 1] == str(firmware.rom_path(owned_root, "kick-test"))

    def should_explain_an_assembler_failure(
        self, owned_root: Path, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        host = host_for(owned_root, FakeMachine, ROM_CONFIG)
        host.assemble.side_effect = None
        host.assemble.return_value = subprocess.CompletedProcess([], 1, "", "error 2 in line 1")

        assert amiga.main(["build", str(project)], host) == 1

        assert "vasm failed:\nerror 2 in line 1" in capsys.readouterr().err

    def should_name_the_variable_for_a_missing_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(native, "tool_path", lambda name: None)

        with pytest.raises(amiga.ProjectError, match="set VASM"):
            amiga.Host().tool("vasm")


# ---- Real checks: vasm, xdftool, Amiberry and the owner's Kickstart ROMs ----


def available_targets() -> list[str]:
    """Standard targets whose firmware is installed in this repository."""
    if any(native.tool_path(name) is None for name in ("amiberry", "vasm")):
        return []
    found = []
    for target in ("a500", "a1200"):
        try:
            firmware.installed(REPOSITORY, target)
            found.append(target)
        except (OSError, firmware.FirmwareError):
            pass
    return found


def real_check(project: Path, target: str, variant: str = "") -> tuple[int, dict[str, str]]:
    argv = ["check", str(project), "--target", target] + (["--variant", variant] if variant else [])
    code = amiga.main(argv)
    name = f"{project.name}-{variant}" if variant else project.name
    report = json.loads((REPOSITORY / "build" / name / target / "report.json").read_text())
    return code, {item["kind"]: item["status"] for item in report["evidence"]}


def require_firmware(target: str) -> None:
    if target not in available_targets():
        pytest.skip(
            f"no verified {target} Kickstart ROM or tools; run sh scripts/bootstrap.sh {target}"
        )


@pytest.mark.integration
@pytest.mark.parametrize("target", ["a500", "a1200"])
class DescribeRealChecks:
    def should_pass_first_screen_on_every_evidence_kind(self, target: str) -> None:
        require_firmware(target)

        code, kinds = real_check(FIRST_SCREEN, target)

        assert code == 0
        assert {kinds[k] for k in ("execution", "memory", "registers", "screen")} == {"PASS"}

    @pytest.mark.parametrize(
        "variant, failing",
        [
            ("wrong-colour", {"memory", "screen"}),
            ("copper-off", {"registers", "screen"}),
            ("no-checkpoint", {"execution"}),
        ],
    )
    def should_fail_each_control_on_the_evidence_it_breaks(
        self, target: str, variant: str, failing: set[str]
    ) -> None:
        require_firmware(target)

        code, kinds = real_check(FIRST_SCREEN, target, variant)

        assert code == 1
        assert {kind for kind, status in kinds.items() if status == "FAIL"} == failing


@pytest.mark.integration
class DescribeRealTemplate:
    def should_reach_the_template_checkpoint(self) -> None:
        require_firmware("a500")

        code, kinds = real_check(REPOSITORY / "template", "a500")

        assert (code, kinds["execution"]) == (0, "PASS")


@pytest.mark.integration
class DescribeRealIsolation:
    def should_resolve_every_amiberry_path_inside_the_repository(self) -> None:
        executable = native.tool_path("amiberry")
        if executable is None:
            pytest.skip("Amiberry is not installed; run uv run python scripts/native.py")
        emulator = amiberry.Amiberry(executable, REPOSITORY, platform.system())

        paths = amiberry.parse_dump(emulator.dump([], "--dump-paths"))

        assert paths["rom_path"].startswith(str(REPOSITORY))
        assert amiberry.outside_paths(paths, REPOSITORY) == {}
