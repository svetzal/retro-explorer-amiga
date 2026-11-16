"""Copy the owner's licensed Kickstart ROMs into ignored `local/roms/` and verify them.

Kickstart ROMs are never downloaded. `firmware.json` records each acceptable
ROM by the SHA-256 of its decoded content, and the owner's products that
supply it. An environment variable (or `.env`) names the folder of each product.

Amiga Forever stores ROMs encrypted: an 11-byte `AMIROMTYPE1` header, then the
ROM XORed with the bytes of `rom.key`, repeated. The starter copies the
encrypted file and `rom.key` unchanged, because Amiberry decrypts the ROM when
`rom.key` is in the same folder. Verification decodes in memory only.
"""

import hashlib
from collections.abc import Mapping
from pathlib import Path

import envfile
from files import atomic_bytes
from pydantic import BaseModel, ConfigDict, Field

MANIFEST = "firmware.json"
ROM_FOLDER = Path("local/roms")
KEY_NAME = "rom.key"
ENCRYPTED_HEADER = b"AMIROMTYPE1"
Sha256 = Field(pattern=r"^[0-9a-f]{64}$")


class FirmwareError(ValueError):
    """Firmware is missing, unreadable or differs from the manifest."""


class Source(BaseModel):
    model_config = ConfigDict(frozen=True)
    product: str
    folder: str


class Location(BaseModel):
    model_config = ConfigDict(frozen=True)
    variable: str
    path: str


class Offer(Location):
    encrypted: bool


class Rom(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str
    size: int = Field(gt=0)
    sha1: str = Field(pattern=r"^[0-9a-f]{40}$")
    sha256: str = Sha256
    offers: list[Offer] = Field(min_length=1)


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True)
    sources: dict[str, Source]
    key: Location
    roms: dict[str, Rom]
    targets: dict[str, list[str]]

    def rom_ids(self, target: str) -> list[str]:
        if target not in self.targets:
            raise FirmwareError(f"No firmware is recorded for target {target!r}")
        return self.targets[target]


def load(root: Path) -> Manifest:
    return Manifest.model_validate_json((root / MANIFEST).read_text())


def decode(data: bytes, key: bytes | None) -> bytes:
    """The ROM content of a plain or Amiga Forever encrypted file."""
    if not data.startswith(ENCRYPTED_HEADER):
        return data
    if not key:
        raise FirmwareError(f"the ROM is encrypted and needs {KEY_NAME} beside it")
    body = data[len(ENCRYPTED_HEADER) :]
    repeated = (key * (len(body) // len(key) + 1))[: len(body)]
    mixed = int.from_bytes(body) ^ int.from_bytes(repeated)
    return mixed.to_bytes(len(body))


def verify(rom: Rom, data: bytes, key: bytes | None, label: str) -> None:
    content = decode(data, key)
    if len(content) != rom.size:
        raise FirmwareError(f"{label}: {len(content)} bytes, expected {rom.size} ({rom.title})")
    found = hashlib.sha256(content).hexdigest()
    if found != rom.sha256:
        raise FirmwareError(f"{label}: SHA-256 {found} differs from {rom.title} in {MANIFEST}")


def rom_path(root: Path, rom_id: str) -> Path:
    return root / ROM_FOLDER / f"{rom_id}.rom"


def key_path(root: Path) -> Path:
    return root / ROM_FOLDER / KEY_NAME


def where_to_get(manifest: Manifest, rom_ids: list[str]) -> str:
    """Plain instructions: which variable to set and which product supplies the ROM."""
    lines = []
    for rom_id in rom_ids:
        rom = manifest.roms[rom_id]
        for offer in rom.offers:
            source = manifest.sources[offer.variable]
            lines.append(
                f"  {rom.title}: set {offer.variable} to {source.folder} "
                f"(product: {source.product}; file: {offer.path})"
            )
    return (
        "Set the variable in your environment or in .env at the repository root "
        "(copy .env.example). Then run setup again:\n" + "\n".join(lines)
    )


def installed(root: Path, target: str) -> tuple[str, Path]:
    """The first acceptable ROM for a standard target that is installed and verified."""
    return first_installed(root, load(root).rom_ids(target), target)


def first_installed(root: Path, rom_ids: list[str], target: str) -> tuple[str, Path]:
    """The first of `rom_ids` that is installed and verified.

    A present but damaged file stops the check; it is never skipped silently.
    """
    manifest = load(root)
    unknown = [rom_id for rom_id in rom_ids if rom_id not in manifest.roms]
    if unknown:
        raise FirmwareError(f"{MANIFEST} records no ROM named {unknown}")
    key = key_path(root).read_bytes() if key_path(root).is_file() else None
    for rom_id in rom_ids:
        path = rom_path(root, rom_id)
        if path.is_file():
            verify(manifest.roms[rom_id], path.read_bytes(), key, str(path))
            return rom_id, path
    raise FirmwareError(
        f"No Kickstart ROM for {target} is installed in {ROM_FOLDER}/. "
        f"Run: uv run python scripts/setup.py --target {target} --firmware-only\n"
        + where_to_get(manifest, rom_ids)
    )


def provision(root: Path, target: str, values: Mapping[str, str]) -> list[str]:
    """Copy each acceptable ROM for the target that an owner source supplies.

    Returns one line per ROM. Raises FirmwareError when no ROM is available.
    """
    manifest = load(root)
    rom_ids = manifest.rom_ids(target)
    report, ready = [], 0
    for rom_id in rom_ids:
        line, ok = _provision_rom(root, manifest, rom_id, values)
        report.append(line)
        ready += ok
    if not ready:
        raise FirmwareError(
            "\n".join([*report, f"No Kickstart ROM for {target} is available.", ""])
            + where_to_get(manifest, rom_ids)
        )
    return report


def _provision_rom(
    root: Path, manifest: Manifest, rom_id: str, values: Mapping[str, str]
) -> tuple[str, bool]:
    rom = manifest.roms[rom_id]
    reasons = []
    for offer in rom.offers:
        folder = envfile.folder(values, offer.variable)
        if folder is None:
            reasons.append(f"{offer.variable} is not set")
            continue
        source = folder / offer.path
        if not source.is_file():
            reasons.append(f"{source} does not exist")
            continue
        data = source.read_bytes()
        key = _source_key(manifest, values) if data.startswith(ENCRYPTED_HEADER) else None
        verify(rom, data, key, str(source))
        _publish(rom_path(root, rom_id), data)
        if key is not None:
            _publish(key_path(root), key)
        return f"{rom_id}: verified {rom.title} from {offer.variable}", True
    return f"{rom_id}: not available ({'; '.join(reasons)})", False


def _source_key(manifest: Manifest, values: Mapping[str, str]) -> bytes:
    folder = envfile.folder(values, manifest.key.variable)
    path = folder / manifest.key.path if folder else None
    if path is None or not path.is_file():
        raise FirmwareError(
            f"An encrypted ROM needs {KEY_NAME}: set {manifest.key.variable} so that "
            f"{manifest.key.path} exists"
        )
    return path.read_bytes()


def _publish(path: Path, data: bytes) -> None:
    """Write a verified file. Refuse to replace a different existing file."""
    if path.is_file():
        if path.read_bytes() == data:
            return
        raise FirmwareError(f"{path} exists and differs; inspect it before you remove it")
    atomic_bytes(path, data)
