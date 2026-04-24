from __future__ import annotations

import pytest


def add_trim_options(parser: pytest.Parser) -> None:
    _addoption_once(
        parser,
        "--trim",
        action="store_true",
        default=False,
        help="Enable compact machine-friendly output format",
    )
    _addoption_once(
        parser,
        "--trim-artifacts",
        action="store_true",
        default=False,
        help=(
            "Write per-failure artifact files (full traceback + captured sections) and emit their paths "
            "as 'artifact:' detail lines"
        ),
    )
    _addoption_once(
        parser,
        "--trim-artifacts-dir",
        action="store",
        default=None,
        metavar="PATH",
        help=(
            "Directory to write failure artifacts into. Relative paths are resolved from pytest rootdir. "
            "Implies --trim-artifacts."
        ),
    )


def _addoption_once(parser: pytest.Parser, *names: str, **kwargs: object) -> None:
    try:
        parser.addoption(*names, **kwargs)
    except ValueError as exc:
        if "already added" not in str(exc):
            raise
