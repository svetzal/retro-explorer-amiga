# Scripts

These tools build, launch and measure. Run each one from the starter folder
with `uv run python scripts/<tool>.py`. The rules for changing them are in
[AGENTS.md](AGENTS.md). The [toolchain guide](../guidance/starter/toolchain.md)
explains the tools and the evidence.

## Commands

| Command | What it does |
| --- | --- |
| `sh scripts/bootstrap.sh <target>` | Prepares Python, the native tools, the reference index and the ROM of one target. Then it runs the doctor |
| `native.py` | Installs Amiberry 8.5.0 and builds vasm 2.0f and vlink 0.18a into `local/tools/` |
| `setup.py --target T --firmware-only` | Copies the target's Kickstart ROM from the owner's product into `local/roms/`, and does a check of it |
| `setup.py --guidance-only` | Writes `local/INDEX.md` without a download |
| `setup.py --list` | Lists the sources in `resources.json` |
| `setup.py --resource ID` | Caches a source. PDF option `--pages FIRST:LAST`. |
| `doctor.py [--target T]` | Checks the tools, the isolation of Amiberry and the target's ROM. It does not boot the machine |
| `amiga.py build <folder>` | Assembles `main.s` and writes `build/<project>/<project>.adf` |
| `amiga.py run <folder>` | Checks the ROM and opens Amiberry in a window |
| `amiga.py snapshot <folder>` | Runs headless to the checkpoint and saves the evidence |
| `amiga.py check <folder>` | Runs each target to the checkpoint and compares the evidence with `expected.py` |

`amiga.py` takes `--target <name>` and `--variant <name>`. Run
`uv run python scripts/amiga.py --help` for the full description.

## Reference downloads and conversion

`resources.json` lists PDFs and web references. PDF entries give a SHA-256
value and a redistribution status. Setup checks the value before it uses the
PDF. It keeps the PDF in `local/references/<id>/source.pdf`.

Docling converts the PDF one page at a time, with OCR. Each page is a
checkpoint, so an interrupted conversion continues from the last complete
page. The result is:

- `local/references/<id>/text.md`: one `## PDF page N` section for each
  converted page, with links to the page images.
- `local/references/<id>/docling-pages/<key>/images/`: a full image of each
  page and an image of each figure.
- `local/INDEX.md`: each source and the PDF pages that setup converted.

Convert a page range first. Convert more pages when you know where the topic
is:

```sh
uv run python scripts/setup.py --resource m68000-um --pages 1:12
```

For a web entry, use `content.url` to name the direct download address.
Set `content.format` to `html` for a web page or `txt` for plain text or code.
Setup saves the original bytes in `local/references/<id>/`. The index links
to the local copy, the cited source and any Wayback copy. Setup reuses the
file on the next run. To get a fresh copy from the same URL, remove the
cached file.

```sh
uv run python scripts/setup.py --resource gloom-renderer
```

A web entry with no `content` gives a citation only. Use this form for a
licensed manual. The index links to that source.

## Measured limits

These limits are measured with Amiberry 8.5.0 on Apple Silicon macOS.

- `firmware.py` decodes an Amiga Forever ROM with `rom.key` in memory and
  compares the SHA-256 of the content. A ROM that it cannot decode or that
  differs fails.
- `doctor.py` reads `--dump-paths` under `local/amiberry-home/`. It ignores
  `compiled_data_dir`, a built-in fallback that the macOS build does not use.
  Paths of an AppImage on Linux are not measured.
- `amiga.py` waits for the checkpoint block at `$100` with `READ_MEM`, with
  warp on. It fails when the magic is present before the program runs, when
  Amiberry exits, or when the time limit ends.
- `amiga.py` compares Amiberry's `--dump-config` with the target table for
  `cpu_model`, `chipset`, `chipmem_size`, `bogomem_size`, `fastmem_size`,
  `ntsc` and `kickstart_rom_file`. It does not compare other settings of the
  quick-start model.
- The screen comparison maps display lines to rows of the screenshot: two
  rows for each line, from line 25 (PAL) or line 20 (NTSC). It ignores 16
  columns at each edge. The horizontal position of a pixel is not measured.
- The tools collect no sound and send no input.
- Each check starts a new emulator at power-on. A run on the `a500` target
  reaches the first-screen checkpoint in about 1.3 s with warp.

## Failure controls

The spec beside `amiga.py` runs these checks on each target whose ROM is
installed. Each one must fail on the named evidence:

| Control | Evidence that fails |
| --- | --- |
| first-screen `wrong-colour` | Memory and screen |
| first-screen `copper-off` | Registers and screen |
| first-screen `no-checkpoint` | Execution |

The unit specs show that `doctor.py` fails on a path outside the repository.
They also show that `firmware.py` refuses a wrong ROM, a short ROM and an
encrypted ROM without its key.
