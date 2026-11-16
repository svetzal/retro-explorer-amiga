"""The bootstrap script's argument handling, without installing anything."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("bootstrap.sh")


def bootstrap(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(SCRIPT), *args], capture_output=True, text=True, check=False)


class DescribeBootstrapArguments:
    def should_explain_its_use(self) -> None:
        result = bootstrap("--help")

        assert result.returncode == 0
        assert "a500|a1200" in result.stdout

    @pytest.mark.parametrize("args", [(), ("a3000",), ("a500", "a1200")])
    def should_refuse_anything_but_one_standard_target(self, args: tuple[str, ...]) -> None:
        result = bootstrap(*args)

        assert result.returncode == 2
