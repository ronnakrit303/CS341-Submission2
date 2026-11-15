"""Keep test scratch files inside this project, isolated for each invocation."""

from uuid import uuid4

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    # A shared Windows Temp/pytest-of-<user> may belong to another account.
    # Choose a fresh directory so pytest never has to scan/delete that tree
    # or a previous invocation's private scratch directory. Honor CLI overrides.
    if config.option.basetemp is None:
        parent = config.rootpath / "tmp" / "pytest-runs"
        parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(parent / uuid4().hex)
