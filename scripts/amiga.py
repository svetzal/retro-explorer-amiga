"""Build, run, snapshot or check an Amiga project folder described by its amiga.toml.

A project folder holds main.s (vasm Motorola syntax), amiga.toml, README.md
and, optionally, expected.py: an independent model of what the program must
leave in memory, in the custom registers and on the screen at its checkpoint.
Amiga facts (machine, firmware, memory, colours) live in those project files.
This tool assembles with vasm, writes a bootable ADF and drives Amiberry.

build    assembles main.s into an AmigaDOS executable and writes a bootable
         OFS floppy, build/<project>/<project>.adf, that runs it at boot.
run      verifies the target's Kickstart ROM and opens Amiberry in a window
         at normal speed for a person. It collects no evidence.
snapshot boots the ADF headless, runs to the checkpoint and saves the
         evidence under build/<project>/<target>/ without comparing it.
check    does the same on every [targets.<name>] table (or --target), compares
         each kind of evidence with expected.py, and reports each kind apart.

check uses the main build. --variant <name> builds with the variant's
defines and runs on its targets. A variant with control = true is a failure
control: its check must fail.

Checkpoints. Amiberry 8.5.0 has no checkpoint that the tool can set before
the program is loaded, so the program reports its own: it writes a long at
$104 (the checkpoint number) and at $108 (an address it wants checked), then
the magic long "CHKP" at $100, and holds there. The tool reads the block
with READ_MEM, requires that the magic was absent at its first read, pauses
the emulator, then reads memory and registers and takes a screenshot.

Evidence boundaries:
- build: vasm and xdftool made the ADF. It does not show the disk boots.
- configuration: Amiberry's --dump-config matched the target table.
- execution: the program wrote the checkpoint block. A screenshot alone never
  establishes this.
- memory and registers: READ_MEM and GET_CUSTOM_REGS at the paused checkpoint.
- screen: Amiberry's SCREENSHOT of the paused frame, compared line by line with
  expected_lines(). It is the emulator's frame, not a monitor or a television.
- sound and input are not supplied by this tool yet.
- visual: never inspected by a person; the report says so.
"""

import argparse
import importlib.util
import inspect
import json
import platform
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Literal

import adf
import amiberry
import firmware
import native
import numpy as np
from amiberry import EmulatorError, Session, field
from files import digest
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = native.ROOT
SETTINGS = "amiga.toml"
MODEL = "expected.py"
MAGIC = int.from_bytes(b"CHKP")
BLOCK = 0x100
# Amiberry 8.5.0 SCREENSHOT geometry, measured with copper colour bands
# (guidance/starter/toolchain.md#evidence-the-tools-collect): two rows for each
# display line, and the first row shows this display line.
TOP_LINE = {"pal": 25, "ntsc": 20}
ROWS_PER_LINE = 2
SIDE_MARGIN = 16  # columns at each edge that can show the black border


class ProjectError(ValueError):
    """The project folder or its settings are invalid."""


class Target(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str
    kickstart: list[str] = Field(min_length=1)
    video: Literal["pal", "ntsc"]
    cpu: str
    chipset: Literal["ocs", "ecs_agnus", "ecs_denise", "ecs", "aga"]
    chip_kib: int = Field(gt=0, multiple_of=512)
    slow_kib: int = Field(ge=0, multiple_of=256)
    fast_kib: int = Field(ge=0, multiple_of=1024)


class Variant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    defines: list[str] = []
    targets: list[str] | None = None
    control: bool = False


class Region(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    at: int | Literal["data"]
    offset: int = 0
    size: int = Field(gt=0, le=1 << 20)


class Check(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    checkpoint: int = Field(default=1, ge=1)
    seconds: float = Field(default=60, gt=0)
    memory: dict[str, Region] = {}


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str = "main.s"
    cpu: str = "68000"
    targets: dict[str, Target] = Field(min_length=1)
    variants: dict[str, Variant] = {}
    check: Check = Check()


class Project(BaseModel):
    model_config = ConfigDict(frozen=True)
    folder: Path
    settings: Settings

    @property
    def name(self) -> str:
        return self.folder.resolve().name

    def output(self, variant: str) -> Path:
        name = f"{self.name}-{variant}" if variant else self.name
        return ROOT / "build" / name


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)
    first_magic: int
    checkpoint: int
    data: int
    seconds: float
    memory: dict[str, bytes]
    registers: dict[str, str]
    screenshot: Path


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    status: Literal["PASS", "FAIL", "SAVED", "NOT CHECKED", "NOT COLLECTED"]
    detail: str


def load_project(folder: Path) -> Project:
    path = folder / SETTINGS
    try:
        settings = Settings.model_validate(tomllib.loads(path.read_text()))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        raise ProjectError(f"{path}: {error}") from error
    for name, variant in settings.variants.items():
        unknown = set(variant.targets or []) - set(settings.targets)
        if unknown:
            raise ProjectError(f"variant {name} names unknown targets: {sorted(unknown)}")
    return Project(folder=folder, settings=settings)


def runs(project: Project, target: str | None, variant: str) -> list[str]:
    """The targets a command uses: --target, the variant's targets, or every target."""
    settings = project.settings
    if variant and variant not in settings.variants:
        raise ProjectError(
            f"unknown variant {variant!r}; amiga.toml has {sorted(settings.variants)}"
        )
    allowed = (settings.variants[variant].targets if variant else None) or list(settings.targets)
    if target is None:
        return allowed
    if target not in allowed:
        raise ProjectError(f"target {target!r} is not one of {allowed}")
    return [target]


def vasm_args(vasm: Path, project: Project, variant: str, out: Path) -> list[str]:
    """`-kick1hunks` keeps relocations in a form that the Kickstart 1.x loader reads."""
    defines = project.settings.variants[variant].defines if variant else []
    return [
        str(vasm),
        "-quiet",
        f"-m{project.settings.cpu}",
        "-Fhunkexe",
        "-kick1hunks",
        "-nosym",
        f"-I{project.folder}",
        *(f"-D{name}=1" for name in defines),
        "-o",
        str(out),
        str(project.folder / project.settings.source),
    ]


def amiberry_args(target: Target, rom: Path, disk: Path) -> list[str]:
    settings = {
        "ntsc": "true" if target.video == "ntsc" else "false",
        "cpu_model": target.cpu,
        "chipset": target.chipset,
        "chipmem_size": str(target.chip_kib // 512),
        "bogomem_size": str(target.slow_kib // 256),
        "fastmem_size": str(target.fast_kib // 1024),
    }
    args = ["--model", target.model, "-r", str(rom), "-0", str(disk)]
    for key, value in settings.items():
        args += ["-s", f"{key}={value}"]
    return args


def configuration_differences(target: Target, rom: Path, config: dict[str, str]) -> list[str]:
    """Settings that Amiberry resolved differently from the target table."""
    wanted = {
        "cpu_model": target.cpu,
        "chipset": target.chipset,
        "chipmem_size": str(target.chip_kib // 512),
        "bogomem_size": str(target.slow_kib // 256),
        "fastmem_size": str(target.fast_kib // 1024),
        "ntsc": "true" if target.video == "ntsc" else "false",
    }
    differences = [
        f"{key}={config.get(key)} (table: {value})"
        for key, value in wanted.items()
        if config.get(key) != value
    ]
    # Amiberry shows a ROM inside its rom_path relative to that folder.
    resolved = config.get("kickstart_rom_file", "")
    folder = Path(config.get("amiberry.rom_path", "/"))
    if not resolved or (folder / resolved).resolve() != rom.resolve():
        differences.append(f"kickstart_rom_file={resolved or None} (table: {rom})")
    return differences


class Clock:
    """Gateway: elapsed wall time and waiting, injectable for specs."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def read_long(session: Session, address: int) -> int:
    reply = session.send("READ_MEM", str(address), "4")
    if reply[0] != "OK" or len(reply) < 2:
        raise EmulatorError(f"READ_MEM {address:#x} failed: {' '.join(reply)}")
    return int(reply[1])


def read_bytes(session: Session, start: int, size: int) -> bytes:
    longs = [read_long(session, start + offset) for offset in range(0, size, 4)]
    return b"".join(value.to_bytes(4) for value in longs)[:size]


def await_socket(session: Session, disk: Path, deadline: float, clock: Clock) -> None:
    """Find this run's socket and check that it reports this run's disk."""
    while not session.find_socket():
        if clock.now() > deadline or not session.running():
            raise EmulatorError(f"Amiberry opened no control socket; see {session.log}")
        clock.sleep(0.1)
    while True:
        try:
            reply = session.send("GET_STATUS")
            break
        except OSError:
            if clock.now() > deadline:
                raise
            clock.sleep(0.1)
    floppy = field(reply, "Floppy0")
    if floppy is None or Path(floppy).resolve() != disk.resolve():
        theirs, session.socket = session.socket, None
        raise EmulatorError(f"the emulator on {theirs} is not this run's: {reply}")


def await_checkpoint(session: Session, number: int, deadline: float, clock: Clock) -> None:
    while True:
        if not session.running():
            raise EmulatorError(f"Amiberry exited before checkpoint {number}; see {session.log}")
        if read_long(session, BLOCK) == MAGIC and read_long(session, BLOCK + 4) == number:
            return
        if clock.now() > deadline:
            raise TimeoutError(f"checkpoint {number} was not reached")
        clock.sleep(0.1)


def observe(
    session: Session, disk: Path, check: Check, evidence: Path, clock: Clock
) -> Observation:
    """Run a started emulator to its checkpoint, pause it and record the evidence."""
    started = clock.now()
    deadline = started + check.seconds
    try:
        await_socket(session, disk, deadline, clock)
        first = read_long(session, BLOCK)
        if first == MAGIC:
            raise EmulatorError("the checkpoint magic was present before the program ran")
        session.send("SET_WARP", "1")
        try:
            await_checkpoint(session, check.checkpoint, deadline, clock)
        except TimeoutError as error:
            session.send("PAUSE")
            session.send("SCREENSHOT", str((evidence / "timeout.png").resolve()))
            raise EmulatorError(f"{error} within {check.seconds:g} s; see {evidence}") from error
        session.send("PAUSE")
        return _record(session, check, evidence, first, clock.now() - started)
    finally:
        session.stop()


def _record(
    session: Session, check: Check, evidence: Path, first: int, seconds: float
) -> Observation:
    data = read_long(session, BLOCK + 8)
    memory = {
        name: read_bytes(
            session, (data if region.at == "data" else region.at) + region.offset, region.size
        )
        for name, region in check.memory.items()
    }
    registers = dict(
        item.split("=", 1) for item in session.send("GET_CUSTOM_REGS")[1:] if "=" in item
    )
    screenshot = (evidence / "screen.png").resolve()
    reply = session.send("SCREENSHOT", str(screenshot))
    if reply[0] != "OK":
        raise EmulatorError(f"SCREENSHOT failed: {' '.join(reply)}")
    return Observation(
        first_magic=first,
        checkpoint=check.checkpoint,
        data=data,
        seconds=seconds,
        memory=memory,
        registers=registers,
        screenshot=screenshot,
    )


def load_expected(folder: Path) -> ModuleType | None:
    """Load the folder's independent expected.py model, if it has one."""
    path = folder / MODEL
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"expected_{folder.resolve().name}", path)
    if spec is None or spec.loader is None:
        raise ProjectError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_model(function: Callable[..., object], **available: object) -> object:
    """Call a model with the keyword arguments its signature names."""
    names = inspect.signature(function).parameters
    return function(**{key: value for key, value in available.items() if key in names})


def compare_memory(expected: dict[str, bytes], observed: dict[str, bytes]) -> Evidence:
    problems = []
    for name, wanted in expected.items():
        found = observed.get(name)
        if found is None:
            problems.append(f"{name}: not read; declare it under [check.memory]")
        elif found[: len(wanted)] != wanted:
            first = next(i for i, pair in enumerate(zip(wanted, found)) if pair[0] != pair[1])
            problems.append(
                f"{name}: byte {first} is {found[first]:#04x}, expected {wanted[first]:#04x}"
            )
    detail = "; ".join(problems) or ", ".join(
        f"{name} ({len(b)} bytes)" for name, b in expected.items()
    )
    return Evidence(kind="memory", status="FAIL" if problems else "PASS", detail=detail)


def compare_registers(expected: dict[str, str], observed: dict[str, str]) -> Evidence:
    problems = [
        f"{name}={observed.get(name)} (expected {value})"
        for name, value in expected.items()
        if observed.get(name, "").upper() != value.upper()
    ]
    detail = "; ".join(problems) or ", ".join(f"{k}={v}" for k, v in expected.items())
    return Evidence(kind="registers", status="FAIL" if problems else "PASS", detail=detail)


def compare_lines(
    expected: dict[int, tuple[int, int, int]], image: np.ndarray, video: str
) -> Evidence:
    """Compare every interior pixel of each expected display line with its colour."""
    height, width, _ = image.shape
    problems = []
    for line, colour in sorted(expected.items()):
        row = (line - TOP_LINE[video]) * ROWS_PER_LINE
        if row < 0 or row + ROWS_PER_LINE > height:
            problems.append(f"line {line} is outside the {height}-row capture")
            continue
        band = image[row : row + ROWS_PER_LINE, SIDE_MARGIN : width - SIDE_MARGIN]
        wrong = int(np.any(band != np.array(colour, dtype=np.uint8), axis=2).sum())
        if wrong:
            found = tuple(int(v) for v in band[0, band.shape[1] // 2])
            problems.append(
                f"line {line}: {wrong} pixels differ (centre {found}, expected {colour})"
            )
    detail = "; ".join(problems[:5]) or f"{len(expected)} display lines match"
    return Evidence(kind="screen", status="FAIL" if problems else "PASS", detail=detail)


def compare(
    model: ModuleType | None, observation: Observation, **available: object
) -> list[Evidence]:
    if model is None:
        return [Evidence(kind="model", status="NOT CHECKED", detail=f"no {MODEL}")]
    available |= {"data": observation.data}
    results = []
    if hasattr(model, "expected_memory"):
        results.append(
            compare_memory(call_model(model.expected_memory, **available), observation.memory)
        )
    if hasattr(model, "expected_registers"):
        results.append(
            compare_registers(
                call_model(model.expected_registers, **available), observation.registers
            )
        )
    if hasattr(model, "expected_lines"):
        image = np.asarray(Image.open(observation.screenshot).convert("RGB"))
        expected = call_model(model.expected_lines, **available)
        results.append(compare_lines(expected, image, str(available["video"])))
    return results


class Host:
    """Gateway bundle: tool discovery, the assembler and the emulator."""

    def tool(self, name: str) -> Path:
        path = native.tool_path(name)
        if path is None:
            raise ProjectError(
                f"{name} is missing; run sh scripts/bootstrap.sh <target> or set {native.VARIABLES[name]}"
            )
        return path

    def assemble(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, check=False, capture_output=True, text=True)

    def emulator(self) -> amiberry.Amiberry:
        return amiberry.Amiberry(self.tool("amiberry"), ROOT, platform.system())

    def clock(self) -> Clock:
        return Clock()


def build(project: Project, variant: str, host: Host) -> Path:
    out = project.output(variant)
    out.mkdir(parents=True, exist_ok=True)
    program = out / project.name[: adf.MAX_NAME]
    result = host.assemble(vasm_args(host.tool("vasm"), project, variant, program))
    if result.returncode != 0:
        raise ProjectError(f"vasm failed:\n{result.stdout}{result.stderr}")
    return adf.bootable_adf(out / f"{project.name}.adf", program, project.name[: adf.MAX_NAME])


def launch_args(project: Project, target_name: str, disk: Path) -> tuple[list[str], Path, str]:
    """Verify the target's firmware and return Amiberry's arguments."""
    target = project.settings.targets[target_name]
    rom_id, rom = firmware.first_installed(ROOT, target.kickstart, target_name)
    return amiberry_args(target, rom, disk), rom, rom_id


def run_target(
    project: Project, target_name: str, variant: str, disk: Path, host: Host
) -> tuple[list[Evidence], Observation | None]:
    """Configure, boot and observe one target. Each failure stops at its own evidence kind."""
    evidence_dir = project.output(variant) / target_name
    target = project.settings.targets[target_name]
    results = [Evidence(kind="build", status="PASS", detail=f"{disk} sha256 {digest(disk)[:16]}")]
    try:
        args, rom, rom_id = launch_args(project, target_name, disk)
    except firmware.FirmwareError as error:
        return [*results, Evidence(kind="firmware", status="FAIL", detail=str(error))], None
    results.append(Evidence(kind="firmware", status="PASS", detail=f"{rom_id} verified"))
    emulator = host.emulator()
    config = amiberry.parse_dump(emulator.dump(args, "--dump-config"))
    differences = configuration_differences(target, rom, config)
    results.append(
        Evidence(
            kind="configuration",
            status="FAIL" if differences else "PASS",
            detail="; ".join(differences)
            or f"{target.model} {target.cpu} {target.chipset} {target.video}",
        )
    )
    if differences:
        return results, None
    try:
        session = emulator.start(args, evidence_dir / "amiberry.log")
        observation = observe(session, disk, project.settings.check, evidence_dir, host.clock())
    except (EmulatorError, OSError) as error:
        return [*results, Evidence(kind="execution", status="FAIL", detail=str(error))], None
    detail = (
        f"checkpoint {observation.checkpoint} reached in {observation.seconds:.1f} s; "
        f"magic absent at first read ({observation.first_magic:#010x})"
    )
    return [*results, Evidence(kind="execution", status="PASS", detail=detail)], observation


def save(evidence_dir: Path, results: list[Evidence], observation: Observation | None) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    record = {"evidence": [r.model_dump() for r in results]}
    if observation is not None:
        for name, data in observation.memory.items():
            (evidence_dir / f"{name}.bin").write_bytes(data)
        record["observation"] = observation.model_dump(mode="json", exclude={"memory"})
    (evidence_dir / "report.json").write_text(json.dumps(record, indent=2) + "\n")


def trailing_evidence() -> list[Evidence]:
    return [
        Evidence(
            kind="sound", status="NOT COLLECTED", detail="this tool does not capture sound yet"
        ),
        Evidence(kind="input", status="NOT COLLECTED", detail="this tool sends no input yet"),
        Evidence(kind="visual", status="NOT CHECKED", detail="not inspected by a person"),
    ]


def report(target: str, variant: str, results: list[Evidence]) -> str:
    title = f"{target}{f' variant {variant}' if variant else ''}"
    return "\n".join([title, *(f"  {r.kind}: {r.status} {r.detail}" for r in results)])


def check_one(project: Project, target: str, variant: str, disk: Path, host: Host) -> bool:
    results, observation = run_target(project, target, variant, disk, host)
    if observation is not None:
        settings = project.settings.targets[target]
        model = load_expected(project.folder)
        results += compare(model, observation, target=target, variant=variant, video=settings.video)
    results += trailing_evidence()
    save(project.output(variant) / target, results, observation)
    print(report(target, variant, results), flush=True)
    if variant and project.settings.variants[variant].control:
        print("  control: this build is a failure control; FAIL is the required result")
    return not any(r.status == "FAIL" for r in results)


def check_command(project: Project, arguments: argparse.Namespace, host: Host) -> int:
    variants = [arguments.variant] if arguments.variant else [""]
    passed = True
    for variant in variants:
        disk = build(project, variant, host)
        for target in runs(project, arguments.target, variant):
            passed &= check_one(project, target, variant, disk, host)
    print("Check: PASS" if passed else "Check: FAIL")
    return 0 if passed else 1


def snapshot_command(project: Project, arguments: argparse.Namespace, host: Host) -> int:
    target = runs(project, arguments.target, arguments.variant)[0]
    disk = build(project, arguments.variant, host)
    results, observation = run_target(project, target, arguments.variant, disk, host)
    if observation is not None:
        results.append(
            Evidence(kind="snapshot", status="SAVED", detail=str(observation.screenshot.parent))
        )
    results += trailing_evidence()
    save(project.output(arguments.variant) / target, results, observation)
    print(report(target, arguments.variant, results))
    return 0 if observation is not None else 1


def run_command(project: Project, arguments: argparse.Namespace, host: Host) -> int:
    target = runs(project, arguments.target, arguments.variant)[0]
    disk = build(project, arguments.variant, host)
    args, _, rom_id = launch_args(project, target, disk)
    print(f"Opening Amiberry: {target} with {rom_id}, {disk}. Close the window to stop.")
    return host.emulator().window(args)


def build_command(project: Project, arguments: argparse.Namespace, host: Host) -> int:
    runs(project, arguments.target, arguments.variant)
    print(build(project, arguments.variant, host))
    return 0


COMMANDS = {
    "build": (build_command, "assemble the project and print the bootable ADF's path"),
    "run": (run_command, "verify the Kickstart ROM and open Amiberry in a window"),
    "snapshot": (snapshot_command, "run headless to the checkpoint and save the evidence"),
    "check": (check_command, "run every target to the checkpoint and compare with expected.py"),
}


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("project", type=Path, help="folder holding amiga.toml")
        command.add_argument("--target", help="a [targets.<name>] table; default: see above")
        command.add_argument("--variant", default="", help="a [variants.<name>] table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, host: Host | None = None) -> int:
    arguments = parse_arguments(argv)
    try:
        project = load_project(arguments.project)
        handler, _ = COMMANDS[arguments.command]
        return handler(project, arguments, host or Host())
    except (ProjectError, firmware.FirmwareError, adf.DiskError, EmulatorError) as error:
        print(f"{arguments.command} failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
