"""Independent model of the first-screen result.

Written from the picture that the README asks for and from the Amiga Hardware
Reference Manual, 3rd edition: chapter 2 (copper MOVE and WAIT instructions),
chapter 3 (BPLCON0 and the colour registers) and appendix B (register
addresses). It is not derived from main.s or from a capture.
"""

# The picture: three background bands, by display line.
BANDS = [(0x00, 0x00F), (0x60, 0xFFF), (0xA0, 0xF80)]  # (first line, 12-bit RGB)
# Display lines to compare: inside the visible area of PAL and NTSC frames.
FIRST_LINE, LAST_LINE = 30, 250

BPLCON0, COLOR00 = 0x100, 0x180  # register offsets from $DFF000


def rgb(colour: int) -> tuple[int, int, int]:
    """The usual 4-bit to 8-bit scaling: component n shows as n * 17 (so $F is 255)."""
    return tuple(((colour >> shift) & 0xF) * 17 for shift in (8, 4, 0))


def move(register: int, value: int) -> bytes:
    return register.to_bytes(2) + value.to_bytes(2)


def wait(line: int) -> bytes:
    """WAIT: VP in bits 15-8, HP in bits 7-1, bit 0 set; mask $FFFE compares all bits."""
    return ((line << 8) | 0x07).to_bytes(2) + (0xFFFE).to_bytes(2)


def expected_memory() -> dict[str, bytes]:
    copper = move(BPLCON0, 0x0200)  # zero bitplanes, colour output enabled
    for index, (line, colour) in enumerate(BANDS):
        if index:
            copper += wait(line)
        copper += move(COLOR00, colour)
    copper += (0xFFFF).to_bytes(2) + (0xFFFE).to_bytes(2)  # end of list
    return {"copper": copper}


def expected_registers(data: int) -> dict[str, str]:
    """Copper DMA is on, and the copper reads the list from its reported address."""
    return {"dma_copper": "1", "COP1LC": f"{data:08X}"}


def expected_lines() -> dict[int, tuple[int, int, int]]:
    lines = {}
    for line in range(FIRST_LINE, LAST_LINE + 1):
        colour = [value for first, value in BANDS if line >= first][-1]
        lines[line] = rgb(colour)
    return lines
