from __future__ import annotations

import pytest

from pytest_trim_bootstrap.options import add_trim_options


def pytest_addoption(parser: pytest.Parser) -> None:
    add_trim_options(parser)


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    if not config.getoption("--trim", default=False):
        return

    from pytest_trim.plugin import pytest_configure as configure_trim_plugin

    configure_trim_plugin(config)
