# Manual setup and recovery

Use this guide to run the setup yourself or to recover from a setup problem.
For an agent-led start, use the [README](../../README.md). Run all commands
from the starter folder.

## Bootstrap

An agent can prepare one target with one command:

```sh
sh scripts/bootstrap.sh a500
```

Use `a1200` for the other standard target. Bootstrap does these steps:

1. Installs uv when it is missing. It uses Homebrew when Homebrew is
   available. If not, it uses the
   [official uv installer](https://docs.astral.sh/uv/getting-started/installation/).
2. Runs `uv sync --locked` to prepare the Python environment.
3. Writes `local/INDEX.md`. It does not download or convert books.
4. Installs Amiberry and builds vasm and vlink into `local/tools/`.
5. Copies the Kickstart ROM of the target from your licensed product into
   `local/roms/`, and does a check of it.
6. Runs the doctor for the target.

If the agent cannot find `uv` after installation, use the path that bootstrap
prints.

Bootstrap stops at the first step that fails. Read the message. Then use the
section below for that step and run bootstrap again. A second run keeps the
files that are already correct.

## Python environment

```sh
uv sync --locked
```

If this fails, make sure that `.python-version` names a Python that uv can
install. Do not install packages into the system Python.

## Native tools

```sh
uv run python scripts/native.py
```

- The build of vasm and vlink needs a C compiler and `make`. On macOS, run
  `xcode-select --install` to get them.
- A checksum failure means that a download differs from the pinned file. Do
  not change the checksum to make the failure stop. Read the
  [installation sources](toolchain.md#installation-sources).
- To use another executable, set `AMIBERRY`, `VASM` or `VLINK` to its path.

## Kickstart firmware

The starter never downloads a Kickstart ROM. Give it the folder of a licensed
product that you own:

1. Copy `.env.example` to `.env`.
2. Set `AMIGA_FOREVER_DIR` to the `Amiga Files` folder of Cloanto Amiga
   Forever. This folder holds `Shared/rom/`.
3. Set `AMIGAOS32_DIR` to the root of the Hyperion AmigaOS 3.2 CD-ROM or
   download, if you have it. This folder holds `ROM/`.
4. Run setup for the target:

   ```sh
   uv run python scripts/setup.py --target a500 --firmware-only
   ```

A variable in the environment overrides the same variable in `.env`. Git
ignores `.env`. Do not commit a ROM, `rom.key` or `.env`.

The [firmware section](toolchain.md#firmware-and-launching) tells which
product supplies each ROM.

### Recover from a firmware failure

| Message | Cause | Recovery |
| --- | --- | --- |
| `<VARIABLE> is not set` | The variable is not in the environment or `.env` | Set it to the folder that the message names |
| `... does not exist` | The folder is wrong, or the product does not have that ROM | Correct the folder. Look for the file name that the message gives |
| `SHA-256 ... differs` or `... bytes, expected` | The file is a different ROM, or it is damaged | Use the file from the product that `firmware.json` names |
| `needs rom.key` | An Amiga Forever ROM without its key | Set `AMIGA_FOREVER_DIR`, so that `Shared/rom/rom.key` exists |
| `exists and differs` | `local/roms/` holds a different file with that name | Inspect the file. Remove it only when you know that it is not needed |

## Emulator isolation

```sh
uv run python scripts/doctor.py --target a500
```

The doctor runs `Amiberry --dump-paths` with the private home folder
`local/amiberry-home/`. It fails when a resolved path is outside the
repository. If it fails, do not run Amiberry by hand. Remove
`local/amiberry-home/` and run the doctor again. The tools write the private
settings again before each run.

## References

```sh
uv run python scripts/setup.py --list
uv run python scripts/setup.py --resource m68000-prm --pages 1:20
```

The first conversion downloads the Docling models. The
[scripts README](../../scripts/README.md) gives the commands.

## Check the starter

After bootstrap, check the example on the target:

```sh
uv run python scripts/amiga.py check examples/first-screen --target a500
```

Then run the full suite:

```sh
uv run pytest --cov -ra
```

The emulator checks in the suite skip each target whose ROM is not
installed. A pass with skipped emulator checks is not a complete check.
