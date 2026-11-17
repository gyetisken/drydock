"""Keep the tests out of the real home directory.

Every test that saved a memory was writing into ~/.drydock/memory, because
the path is derived from the home directory and nothing told it otherwise.
One of them deliberately writes a corrupt file, which the next real run then
had to survive.
"""

import pytest


@pytest.fixture(autouse=True)
def somewhere_else(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path_factory.mktemp("home")))
