"""Owner settings from the environment and .env."""

from pathlib import Path

import pytest
from envfile import EnvFileError, folder, parse, settings


class DescribeParse:
    def should_read_keys_comments_exports_and_quotes(self) -> None:
        text = "# comment\n\nexport A=1\nB='two words'\nC=\"x # y\"\nD=plain # note\nE=\n"

        assert parse(text) == {"A": "1", "B": "two words", "C": "x # y", "D": "plain", "E": ""}

    @pytest.mark.parametrize("line", ["NOT A LINE", "1BAD=x", "=value"])
    def should_reject_a_line_that_is_not_key_value(self, line: str) -> None:
        with pytest.raises(EnvFileError, match="line 1"):
            parse(line)


class DescribeSettings:
    def should_let_a_real_variable_override_the_file(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("A=file\nB=file\n")

        merged = settings(tmp_path, {"A": "real", "B": ""})

        assert merged == {"A": "real", "B": "file"}

    def should_work_without_a_file(self, tmp_path: Path) -> None:
        assert settings(tmp_path, {"A": "real"}) == {"A": "real"}


class DescribeFolder:
    def should_expand_the_home_directory(self) -> None:
        assert folder({"X": "~/amiga"}, "X") == Path.home() / "amiga"

    @pytest.mark.parametrize("values", [{}, {"X": ""}])
    def should_return_none_when_unset_or_empty(self, values: dict[str, str]) -> None:
        assert folder(values, "X") is None
