"""Keep the tests out of the real home directory, and off the models.

Every test that saved a memory was writing into ~/.drydock/memory, because
the path is derived from the home directory and nothing told it otherwise.
One of them deliberately writes a corrupt file, which the next real run then
had to survive.
"""

import pytest


@pytest.fixture(autouse=True)
def somewhere_else(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path_factory.mktemp("home")))
    monkeypatch.setenv("DRYDOCK_PROJECTS", str(tmp_path_factory.mktemp("projects")))
    # And no real worker, ever. A fixture that believed it had stubbed
    # the stations left one unstubbed, and the suite drew a logo with a
    # real model for real money. Care was the only thing stopping it.
    monkeypatch.setenv("DRYDOCK_NO_WORKERS", "1")
