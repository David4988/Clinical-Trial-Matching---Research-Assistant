import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.repository.json_repo import JsonRepository  # noqa: E402
from app.service import ScreeningService  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    """A throwaway store so tests never touch the demo data file."""
    return JsonRepository(tmp_path / "store.json")


@pytest.fixture
def service(repo):
    return ScreeningService(repository=repo)
