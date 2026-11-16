"""Read owner settings from the environment, with `.env` at the repository root as a fallback.

Tracked files never hold a path on one person's disk. A setting names an
environment variable. Its value comes from the real environment or, when the
variable is unset there, from `.env`, which git ignores.

The `.env` format is the common subset: `KEY=VALUE` lines, an optional
`export ` prefix, blank lines and `#` comment lines. A value can be in single
or double quotes. An unquoted value ends at ` #`. There is no substitution.
"""

import re
from collections.abc import Mapping
from pathlib import Path

ENV_FILE = ".env"
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class EnvFileError(ValueError):
    """A line of `.env` is not `KEY=VALUE`."""


def parse(text: str) -> dict[str, str]:
    values = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.removeprefix("export ").lstrip().partition("=")
        key = key.strip()
        if not separator or not KEY.fullmatch(key):
            raise EnvFileError(f"{ENV_FILE} line {number} is not KEY=VALUE: {raw!r}")
        values[key] = _unquote(value.strip())
    return values


def settings(root: Path, environ: Mapping[str, str]) -> dict[str, str]:
    """Merge `.env` and the real environment. A non-empty real variable wins."""
    path = root / ENV_FILE
    from_file = parse(path.read_text()) if path.is_file() else {}
    return from_file | {key: value for key, value in environ.items() if value}


def folder(values: Mapping[str, str], name: str) -> Path | None:
    """The folder a variable names, with `~` expanded, or None when it is unset or empty."""
    value = values.get(name, "")
    return Path(value).expanduser() if value else None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    comment = value.find(" #")
    return value[:comment].rstrip() if comment >= 0 else value
