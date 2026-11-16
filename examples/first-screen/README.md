# Set the background with a copper list

This example shows how to put a known picture on the screen with the copper.
The copper is the display coprocessor. A list of copper instructions in chip
RAM changes the background colour on three bands of lines. The program then
holds the picture. The example has no bitplanes, no input, no sound and no
timing.

The same program runs on the `a500` target (OCS) and the `a1200` target (AGA).

## The copper instructions

The copper reads a list of 32-bit instructions with DMA. It starts again at
the address in `COP1LC` at the start of each frame.

| Instruction | First word | Second word | Effect |
| --- | --- | --- | --- |
| MOVE | Register offset from `$DFF000`, bit 0 clear | Value | Write the value to the register |
| WAIT | Line in bits 15 to 8, position in bits 7 to 1, bit 0 set | Mask, `$FFFE` to compare all bits | Stop until the beam reaches the position |
| End | `$FFFF` | `$FFFE` | Wait for a line that never comes |

| Register | Offset | Use in this example |
| --- | --- | --- |
| `COLOR00` | `$180` | Background colour, 12-bit `$0RGB` |
| `BPLCON0` | `$100` | `$0200`: no bitplanes, colour output on |
| `COP1LC` | `$080` | Address of the list (long) |
| `COPJMP1` | `$088` | A write starts the copper at `COP1LC` immediately |
| `DMACON` | `$096` | `$0020` clears SPREN, which stops sprite DMA |

The picture:

| Lines | Colour | `COLOR00` |
| --- | --- | --- |
| From the top to `$5F` | Blue | `$00F` |
| `$60` to `$9F` | White | `$FFF` |
| `$A0` to the bottom | Orange | `$F80` |

## Where the example is

The example is the two marked parts of [main.s](main.s):

1. `; >>> EXAMPLE 1 of 2`: the copper list at the `copper` label. It is in a
   `DATA_C` section, because the copper reads only chip RAM.
2. `; >>> EXAMPLE 2 of 2`: the start steps:
   1. Call `Forbid`. Then no other task can load a new display.
   2. Clear SPREN in `DMACON`. Then the mouse pointer sprite does not show.
   3. Write the address of the list to `COP1LC`.
   4. Write to `COPJMP1` to start the list in this frame.

The program keeps the interrupts, the stack and the other DMA channels that
the firmware set. The code under `; --- CONTEXT` writes the checkpoint block
and holds the program. That code is only for the check. Remove it in a real
project, or keep it to check the project.

Other ways to show a colour:

- Write `COLOR00` from the CPU. The system copper list writes the colour again
  at each frame, so the colour does not stay.
- Show a bitplane picture. That is a different practice.

## See and check it

Open a terminal in the starter folder. Run one line:

```sh
uv run python scripts/amiga.py run examples/first-screen                 # a500
uv run python scripts/amiga.py run examples/first-screen --target a1200  # a1200
uv run python scripts/amiga.py check examples/first-screen
```

`run` opens Amiberry in a window. Close the window to stop it.

`check` runs on both targets in [amiga.toml](amiga.toml). Each target uses
PAL. On each target it compares these results with [expected.py](expected.py):

- Memory: the 28 bytes of the copper list at the address that the program
  writes at `$108`.
- Registers: copper DMA is on, and `COP1LC` holds the address of the list.
- Screen: each pixel of display lines 30 to 250 in Amiberry's screenshot, away
  from the border columns, has the colour of its band.

The check shows that the emulated machine ran the list and drew the bands. It
does not show the result on a monitor, a television or a physical Amiga. A
person did not inspect the picture.

## Failure controls

Each control is a variant in [amiga.toml](amiga.toml). Its check must fail.
The spec beside `scripts/amiga.py` runs each one on each target.

| Variant | Change | Evidence that must fail |
| --- | --- | --- |
| `wrong-colour` | Green, not orange, from line `$A0` | Memory and screen |
| `copper-off` | The list is in memory, but `COP1LC` is not written | Registers and screen |
| `no-checkpoint` | The program does not write the checkpoint block | Execution |

```sh
uv run python scripts/amiga.py check examples/first-screen --variant wrong-colour
```

## Sources

The Amiga Hardware Reference Manual is licensed material, and
`resources.json` does not list it. These facts come from the third edition:

- Chapter 2, "Coprocessor Hardware": the MOVE and WAIT instructions, the end
  of a list, `COP1LC` and `COPJMP1`.
- Chapter 3, "Playfield Hardware": `BPLCON0` and the colour registers.
- Appendix B: the register addresses.

Open question: the page numbers are not recorded. Check them against a copy
that the owner has.
