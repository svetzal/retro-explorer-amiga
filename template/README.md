# Project name

Replace this file with the README of your project. Copy the `template/`
folder to `projects/<name>/` first. Name the folder after the idea of the
owner.

The program in this folder reports checkpoint 1 and returns to AmigaDOS. It
shows nothing. Replace it with your program.

## What the owner asked for

Write the request of the owner here, in plain words.

## How to run it

Commands start in the starter folder:

```sh
uv run python scripts/amiga.py run projects/<name>
uv run python scripts/amiga.py check projects/<name>
```

The `run` command opens Amiberry in a window. Close the window to stop it.

## Contract

Write each item before you write hardware-dependent code. Keep `amiga.toml`
the same as this list. Mark a starter default as a default, not as a choice
of the owner.

- Amiga model: Amiga 500 (starter default)
- Amiberry model: `A500` (starter default)
- CPU: 68000 at the stock clock (starter default)
- Chipset: OCS (starter default)
- Memory: 512 KiB chip RAM and 512 KiB slow RAM (starter default)
- Video standard: NTSC (starter default)
- Firmware: Kickstart 1.3, `kick13` (starter default)
- Deliverable: a bootable OFS floppy image whose startup-sequence runs the
  program (starter default)
- Controls: none yet
- Checkpoint: number 1, reported by the program (starter default)

## Check

`amiga.toml` names the checkpoint number that the check waits for. Read
[evidence the tools collect](../guidance/starter/toolchain.md#evidence-the-tools-collect).

Add `expected.py` with an independent model of the result when the program
draws or stores something that you can check. Read
[development practice](../guidance/starter/development.md) for the files and
the commands.
