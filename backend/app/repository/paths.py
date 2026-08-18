"""Where the JSON stores live.

Local development writes into `backend/data/`, which is what the repository has
always done and what the tests and scripts expect. A deployment sets `DATA_DIR`
to a directory that survives restarts — on Render, the mount point of a
persistent disk — and the same files are written there instead.

Only the location is configurable. The file names, the JSON shapes and the
repository semantics are unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Absolute path of `backend/data`, independent of the working directory.
LOCAL_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

ENV_VAR = "DATA_DIR"


def data_dir() -> Path:
    """The directory the JSON stores are read from and written to."""
    configured = os.environ.get(ENV_VAR, "").strip()
    return Path(configured).expanduser() if configured else LOCAL_DATA_DIR
