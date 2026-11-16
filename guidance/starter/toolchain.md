# Amiga development toolchain

Load this file before you assemble, build a disk image, or launch the
emulator. First read the contract of the project in
`projects/<name>/README.md`. Do not infer the model, the memory, the video
standard or the Kickstart from the files that are installed.

## Tool roles

| Tool | Executable | Version | Purpose |
| --- | --- | --- | --- |
| vasm | `vasmm68k_mot` | 2.0f | Assembles 68000 source (Motorola syntax) into an AmigaDOS executable |
| vlink | `vlink` | 0.18a | Links object files. A one-file program does not need it |
| amitools | `xdftool` (Python) | 0.9.0 | Writes the bootable floppy image (ADF) |
| Amiberry | `Amiberry` | 8.5.0 | Emulates the Amiga. Its control socket lets the tools drive it |

Amiberry, vasm and vlink are host executables in ignored `local/tools/`.
amitools is in the uv Python environment. Run every tool through
`scripts/amiga.py`. Do not write a launcher.

To make a check of the tools, the isolation of the emulator and the firmware,
run:

```sh
uv run python scripts/doctor.py --target a500
```

The doctor does not boot the machine. It returns nonzero in these cases:

- A tool is missing.
- Amiberry resolves a path outside the repository.
- The Kickstart ROM of the target is missing or wrong.

Without `--target`, the doctor says that it did not check the firmware.

To use another executable, set `AMIBERRY`, `VASM` or `VLINK` to its path.
Do not write a private path of a developer into a tracked file.

### Installation sources

`sh scripts/bootstrap.sh <target>` runs `uv run python scripts/native.py`.
The installer checks each download against a SHA-256 value that
`scripts/native.py` records. It does not install a file that differs.

- Amiberry comes from the
  [v8.5.0 GitHub release](https://github.com/BlitterStudio/amiberry/releases/tag/v8.5.0).
  The checksums come from the `SHA256SUMS` file of the release. On macOS the
  installer copies `Amiberry.app` out of the disk image with `ditto`, which
  keeps the signature.
- vasm and vlink are built from source with the host C compiler and `make`.
  In November 2026 their authors' host stopped serving the versioned
  archives. The installer tries that host first. Then it tries an Internet
  Archive copy of the same archive. The checksum decides, not the host.

To move to a newer release, change the version, the URLs and the checksums in
`scripts/native.py`. Then run the full suite on each target.

## Supported hosts

| Host | Status |
| --- | --- |
| Apple Silicon macOS | Measured: bootstrap, doctor and every check in this guide |
| Linux x86_64 and aarch64 | Written: the installer picks the Amiberry AppImage. Not run yet |
| Intel macOS | Not supported. Bootstrap stops before it installs anything |

The build of vasm and vlink needs a C compiler and `make`. On macOS, the
Xcode command line tools supply them.

An AppImage runs from a mount under `/tmp`. It is not measured whether the
doctor accepts the data paths of an AppImage.

## Firmware and launching

Kickstart ROMs are licensed. The starter never downloads them. The owner
points the starter at a licensed product that they have, and the starter
copies each ROM from there.

Set one or both variables. Put them in the environment, or in `.env` at the
repository root. Copy `.env.example` to `.env` to start. A variable in the
environment overrides `.env`. Git ignores `.env`.

| Variable | Product | Folder to give | Supplies |
| --- | --- | --- | --- |
| `AMIGA_FOREVER_DIR` | Cloanto Amiga Forever | The `Amiga Files` folder, which holds `Shared/rom/` | Kickstart 1.3 (`a500`), Kickstart 3.1 (`a1200`) and `rom.key` |
| `AMIGAOS32_DIR` | Hyperion AmigaOS 3.2 | The root of the CD-ROM or download, which holds `ROM/` | Kickstart 3.2 (`a1200`) |

Then copy the ROM of a target and do a check of it:

```sh
uv run python scripts/setup.py --target a500 --firmware-only
```

When a variable is not set or a file is missing, setup stops. It names the
variable to set and the product that supplies the ROM.

`firmware.json` records each acceptable ROM:

| ROM | Title | SHA-1 of the content | Source |
| --- | --- | --- | --- |
| `kick13` | Kickstart 1.3 (34.5), A500 | `891e9a54...` | Amiga Forever, `Shared/rom/amiga-os-130.rom` |
| `kick31-a1200` | Kickstart 3.1 (40.68), A1200 | `e2154572...` | Amiga Forever, `Shared/rom/amiga-os-310-a1200.rom` |
| `kick32-a1200` | Kickstart 3.2 (47.96), A1200 | `5b298287...` | AmigaOS 3.2, `ROM/kicka1200.rom` |

The checksums are of the ROM content, not of the file. Amiga Forever encrypts
its ROMs with its `rom.key` file. The starter decodes the content in memory to
check it. It copies the encrypted file and `rom.key` unchanged into
`local/roms/`, because Amiberry decrypts the ROM when `rom.key` is in the same
folder. Use the SHA-1 values to compare a ROM with other ROM lists.

Hyperion AmigaOS 3.1.4 is not recorded yet. To add it, add its checksums from
a copy that you own and a variable for its folder.

Setup refuses a ROM whose content differs from `firmware.json`. It refuses to
replace a different file that is already in `local/roms/`. Inspect that file
before you remove it.

Before each launch, `scripts/amiga.py` checks the installed ROM again. It
stops with the recovery command when the check fails.

### Launching

`scripts/amiga.py` starts Amiberry with a private home folder,
`local/amiberry-home/`. Its `amiberry.conf` sets the ROM, content and save
paths inside the repository. Amiberry never reads the owner's own Amiberry
settings. For the `a500` target, the command line is equal to:

```sh
HOME=local/amiberry-home Amiberry --model A500 -r local/roms/kick13.rom \
  -0 build/<project>/<project>.adf -s ntsc=true -s cpu_model=68000 \
  -s chipset=ocs -s chipmem_size=1 -s bogomem_size=2 -s fastmem_size=0 -G
```

`chipmem_size` counts 512 KiB units, `bogomem_size` counts 256 KiB units and
`fastmem_size` counts MiB.

### Standard targets

| Target | Model | Kickstart | CPU | Chipset | Memory | Video |
| --- | --- | --- | --- | --- | --- | --- |
| `a500` (default) | Amiga 500 | 1.3 | 68000 | OCS | 512 KiB chip, 512 KiB slow | NTSC |
| `a1200` | Amiga 1200 | 3.1, or 3.2 | 68020 | AGA | 2 MiB chip | NTSC |

NTSC is a starter default. It is not a fact about the owner's machine. Record the video standard of the owner in the
contract. Use `video = "ntsc"` when the owner's machine or request is PAL.
The first-screen check passes on both standards.

The `a1200` target accepts Kickstart 3.1 or 3.2. The check uses the first ROM
in the list that is installed, and the report names it.

### Target tables

Copy the table of the target into `amiga.toml`. Change a value only when the
contract of the project records a different machine. Then record the reason
in the contract.

```toml
[targets.a500]
model = "A500"
kickstart = ["kick13"]
video = "ntsc"
cpu = "68000"
chipset = "ocs"
chip_kib = 512
slow_kib = 512
fast_kib = 0

[targets.a1200]
model = "A1200"
kickstart = ["kick31-a1200", "kick32-a1200"]
video = "ntsc"
cpu = "68020"
chipset = "aga"
chip_kib = 2048
slow_kib = 0
fast_kib = 0
```

| Key | Meaning |
| --- | --- |
| `model` | The Amiberry quick-start model. It sets the compatibility settings |
| `kickstart` | ROM names from `firmware.json`, in order of preference |
| `video` | `pal` or `ntsc` |
| `cpu` | `68000`, `68010`, `68020`, `68030`, `68040` or `68060` |
| `chipset` | `ocs`, `ecs_agnus`, `ecs_denise`, `ecs` or `aga` |
| `chip_kib`, `slow_kib`, `fast_kib` | Memory sizes in KiB |

## Project settings

A project folder holds `main.s`, `amiga.toml`, `README.md` and, when the
program has a result to compare, `expected.py`.

```toml
source = "main.s"     # vasm Motorola syntax
cpu = "68000"         # the CPU that vasm assembles for (-m68000)

[targets.a500]        # one table for each target; the first is the default
# ...

[variants.no-death]   # one table for each build variant
defines = ["NO_DEATH"]   # vasm defines each symbol as 1
targets = ["a500"]       # optional: the targets that the variant runs on
control = true           # optional: a failure control, which must fail

[check]
checkpoint = 1        # the checkpoint number that the check waits for
seconds = 60          # the time limit for one run, in host seconds
memory = { board = { at = "data", size = 64 }, score = { at = 0x7f000, size = 4 } }
```

- `build` assembles with `-Fhunkexe -kick1hunks`. The second option keeps
  the relocations in the form that the Kickstart 1.x loader reads. Then
  `build` writes `build/<project>/<project>.adf`. The disk uses OFS and the
  Kickstart 1.x boot block. Its `s/startup-sequence` runs the program.
  Kickstart 3.1 and 3.2 boot the same disk.
- A variant builds into `build/<project>-<variant>/`.
- `check` without `--variant` checks the main build only. Run each control
  with `--variant <name>`.
- A `[check.memory]` entry reads `size` bytes at `at` plus `offset`. The value
  `"data"` means the address that the program writes at `$108`.

### The checkpoint block

Amiberry 8.5.0 cannot stop at an address that the tools know before the
program loads. AmigaDOS loads the program at an address that changes. Thus
the program reports its own checkpoint:

1. Write the checkpoint number as a long at `$104`.
2. Write an address for the check to read as a long at `$108`, or zero.
3. Write the long `"CHKP"` at `$100`. Write it last.
4. Hold at the checkpoint until the check pauses the machine. A loop, or a
   return to AmigaDOS, holds the block.

The block uses the 68000 user interrupt vectors at `$100` to `$10B`. Amiga
system software does not use them.
Mark the code that writes the block as code for the check only.

## Evidence the tools collect

`scripts/amiga.py check` reports each kind of evidence on its own line. A
failure of one kind does not hide the others.

| Evidence | How the tool collects it | What it shows |
| --- | --- | --- |
| Build | vasm and xdftool | The ADF exists. It does not show that the disk boots |
| Firmware | Decode and checksum before each launch | The ROM content agrees with `firmware.json` |
| Configuration | `--dump-config` with the arguments of the run | Amiberry resolved the model, CPU, chipset, memory, video and ROM of the table |
| Execution | `READ_MEM` polls the checkpoint block | The program wrote the checkpoint. The magic was absent at the first read |
| Memory | `READ_MEM`, one long at a time, after `PAUSE` | Bytes at the paused checkpoint |
| Registers | `GET_CUSTOM_REGS` after `PAUSE` | `DMACON`, `INTENA`, `INTREQ`, the DMA bits, `COP1LC` and `COP2LC` |
| Screen | `SCREENSHOT` after `PAUSE` | Amiberry's frame, compared line by line with `expected_lines()` |
| Sound | Not collected | |
| Input | Not sent | |
| Visual | Never | A person did not look at the picture |

The tool keeps each run's evidence in `build/<project>[-<variant>]/<target>/`:
`report.json`, `screen.png`, one `.bin` file for each memory region and
`amiberry.log`. When the checkpoint does not come, it keeps `timeout.png`.

A screenshot alone does not show that the program reached its checkpoint.
The check requires the checkpoint block before it records anything.

### What `expected.py` supplies

Each function is optional. The tool passes only the arguments that the
function names: `target`, `variant`, `video` and `data` (the address at
`$108`).

| Function | Returns | Compared with |
| --- | --- | --- |
| `expected_memory()` | `{name: bytes}` | The `[check.memory]` region of each name |
| `expected_registers()` | `{field: text}` | The `GET_CUSTOM_REGS` fields. Case does not matter |
| `expected_lines()` | `{display line: (r, g, b)}` | Every pixel of the line in the screenshot, except 16 columns at each edge |

Write `expected.py` from the request and from sourced facts. Never copy a
value from a capture into it.

### Screenshot geometry

These values are measured with Amiberry 8.5.0 on Apple Silicon macOS, with a
copper list that changes the background at known lines:

| Video | Capture size | Display line of the first row |
| --- | --- | --- |
| PAL, A500 | 752 x 576 | 25 |
| PAL, A1200 | 756 x 576 | 25 |
| NTSC, A500 | 752 x 486 | 20 |

Each display line fills two rows. The first two rows and the first two
columns are black. NTSC captures are black from column 738. A 4-bit colour
component `n` shows as `n * 17`.

`expected_lines()` compares whole lines only. The horizontal position of a
lowres pixel in the capture is not measured yet, so a bitplane picture needs
more work in the tool.

### Measured abilities of the control socket

Measured with Amiberry 8.5.0 on Apple Silicon macOS:

- `READ_MEM <address> 4` returns a big-endian long in decimal. The tool reads
  chip RAM and the low vectors with it.
- `GET_STATUS` names the floppy in `DF0:`. The tool uses it to confirm that
  the socket belongs to its own run.
- `SET_WARP 1` runs the machine as fast as the host can. The first-screen
  checkpoint comes in about 1.3 s on the `a500` target.
- `PAUSE` stops the machine. Memory, registers and the screenshot then come
  from the same moment.
- `SET_BREAKPOINT <address>` stops the CPU at that address. `DEBUG_STATUS`
  then reports `stopped=1`. The tools do not use it, because the load address
  of the program is not known before the program runs.
- In the earlier `amiga-llm` work with the same release, `FRAME_ADVANCE`
  replied `OK` but ran no frame, and `SEND_KEY` and `SEND_MOUSE` reached a
  program. The tools here do not use them yet.

### Abilities that still need work

| Ability the pattern needs | Status |
| --- | --- |
| Configure the target and load the deliverable | Supplied |
| Start from a known state | Supplied: each run starts a new emulator at power-on |
| Run to a meaningful checkpoint | Supplied: the program reports it |
| Supply input | Not supplied. `SEND_KEY` exists in Amiberry |
| Inspect memory and registers | Supplied |
| Capture the screen | Supplied, for whole display lines |
| Capture sound | Not supplied. SDL's disk audio driver is a possible route |
| Step frame by frame | Not supplied. `FRAME_ADVANCE` does not run a frame |
| Compare with independent expectations | Supplied |
| Report each kind of evidence | Supplied |

A result in Amiberry does not establish the behaviour of a physical Amiga.
